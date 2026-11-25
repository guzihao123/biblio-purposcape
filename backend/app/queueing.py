import hashlib
import json
import re
from datetime import datetime, timezone

import redis
from redis.exceptions import RedisError
from rq import Queue, SimpleWorker, Worker

try:
    from openai import RateLimitError
except ImportError:
    RateLimitError = ()

from app.config import get_settings
from app.db import engine
from app.db import SessionLocal
from app.models import InviteSession, Task, TaskAnswer, TaskEvent, TaskJob, TaskProgress
from app.rate_limit import RATE_LIMIT_MESSAGE, get_rate_limiter
from sqlalchemy.exc import DBAPIError
import time as _time
from app.recovery import (
    install_worker_log_redaction,
    protected_traceback,
    redact_sensitive_text,
)
from app.schemas import CardId, TaskState


install_worker_log_redaction()

QUEUE_NAME = 'landscape'
SAFE_FAILURE_MESSAGE = '任务执行失败，请稍后重试。'
SAFE_ENQUEUE_MESSAGE = '任务暂时无法排队，请稍后重试。'

# Later retrieval/delivery tasks register their real services here. Keeping the
# registry empty prevents an unimplemented stage from reporting false success.
STAGE_SERVICES = {}

_STAGE_MESSAGES = {
    'search': {
        'queued': '等待检索与论文池整理',
        'started': '正在检索与整理论文池',
        'completed': '检索与论文池整理完成',
    },
}


class StageExecutionError(RuntimeError):
    """Safe exception exposed to RQ after the original traceback is protected."""


class ProtectedWorkerMixin:
    def handle_job_failure(self, job, queue, started_job_registry=None, exc_string=''):
        return super().handle_job_failure(
            job,
            queue,
            started_job_registry=started_job_registry,
            exc_string=redact_sensitive_text(exc_string),
        )


class ProtectedWorker(ProtectedWorkerMixin, Worker):
    pass


class ProtectedSimpleWorker(ProtectedWorkerMixin, SimpleWorker):
    pass


class StageRateLimitError(RuntimeError):
    def __init__(self, result):
        super().__init__(result.message)
        self.result = result


def _provider_retry_after(error):
    if not isinstance(error, RateLimitError):
        return None
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', None)
    value = headers.get('Retry-After') if headers is not None else None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}', value.strip()):
        return None
    seconds = int(value.strip())
    return seconds if seconds >= 1 else None


class QueueEnqueueError(RuntimeError):
    """Safe enqueue failure exposed after persistent state is reconciled."""


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _event_details(stage, input_hash):
    return {
        'stage': stage,
        'input_hash': input_hash,
        'timestamp': _timestamp(),
    }


def _stage_input(db, task_id, stage):
    answers = (
        db.query(TaskAnswer)
        .filter_by(task_id=task_id)
        .order_by(TaskAnswer.id)
        .all()
    )
    return {
        'task_id': task_id,
        'stage': stage,
        'answers': [
            {'card_id': answer.card_id, 'value': answer.value}
            for answer in answers
        ],
    }


def _hash_input(stage_input):
    canonical = json.dumps(
        stage_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _progress_for(db, task_id):
    progress = db.get(TaskProgress, task_id)
    if progress is None:
        progress = TaskProgress(task_id=task_id, message='')
        db.add(progress)
        db.flush()
    return progress


def _latest_stage_job(db, task_id, stage):
    return (
        db.query(TaskJob)
        .filter_by(task_id=task_id, kind=stage)
        .order_by(TaskJob.answer_id.desc())
        .first()
    )


def _set_job_status(db, task_id, stage, status):
    job = _latest_stage_job(db, task_id, stage)
    if job is not None:
        job.status = status


def _message(stage, kind):
    return _STAGE_MESSAGES.get(stage, {}).get(
        kind,
        {
            'queued': f'等待执行阶段：{stage}',
            'started': f'正在执行阶段：{stage}',
            'completed': f'阶段完成：{stage}',
        }[kind],
    )


def record_event(db, task_id, kind, payload=None):
    """Persist one ordered task event in the caller's transaction."""
    event = TaskEvent(
        task_id=task_id,
        event_type=kind,
        payload=payload or {},
    )
    db.add(event)
    db.flush()
    return event


def _record_failure(
    db,
    task_id,
    stage,
    input_hash,
    protected_traceback,
    event_type='failed',
    message=SAFE_FAILURE_MESSAGE,
    retry_after=None,
):
    task = db.get(Task, task_id)
    if task is None:
        return
    message = redact_sensitive_text(message or SAFE_FAILURE_MESSAGE)
    payload = _event_details(stage, input_hash)
    payload.update(
        message=message,
        retryable=True,
        retry_action={'action': 'retry_stage', 'stage': stage},
    )
    if retry_after is not None:
        payload['retry_after'] = retry_after
    record_event(db, task_id, event_type, payload)

    progress = _progress_for(db, task_id)
    progress.stage = stage
    progress.input_hash = input_hash
    progress.message = message
    progress.checkpoint = None
    progress.traceback = protected_traceback
    task.state = TaskState.ERROR.value
    _set_job_status(db, task_id, stage, 'failed')
    db.commit()


def _record_failure_in_new_session(
    task_id,
    stage,
    input_hash,
    protected,
    session_factory=None,
    **kwargs,
):
    """Best-effort failure persistence isolated from the aborted worker transaction."""
    factory = session_factory or SessionLocal
    try:
        with factory() as failure_db:
            _record_failure(
                failure_db,
                task_id,
                stage,
                input_hash,
                protected,
                **kwargs,
            )
    except Exception:
        # The original safe exception is still raised. If the database is also
        # unavailable, no raw database/Redis diagnostic can cross the RQ boundary.
        pass


def _consume_stage_quotas(db, task, stage, input_hash):
    operations = {
        'search': ('retrieval', 'model'),
        'generate': ('model',),
    }.get(stage, ())
    if not operations:
        return
    owner = db.get(InviteSession, task.session_id)
    source_ip = (owner.client_ip if owner is not None else '') or 'unknown'
    limiter = get_rate_limiter()
    for operation in operations:
        result = limiter.consume(
            operation,
            session_id=task.session_id,
            source_ip=source_ip,
            idempotency_key=f'{task.id}:{stage}:{input_hash}',
        )
        if not result.allowed:
            raise StageRateLimitError(result)


def _duplicate_checkpoint(db, task_id, stage, input_hash):
    """Return an existing result for an at-least-once RQ duplicate, if any."""
    job = _latest_stage_job(db, task_id, stage)
    progress = db.get(TaskProgress, task_id)
    if job is None or progress is None:
        return False, None
    same_execution = progress.stage == stage and progress.input_hash == input_hash
    if not same_execution:
        return False, None
    if job.status == 'completed' and progress.checkpoint is not None:
        return True, progress.checkpoint
    if job.status == 'started':
        # A concurrent RQ duplicate must not invoke a paid/remote service twice.
        # The original execution remains responsible for its terminal state.
        return True, progress.checkpoint or {}
    return False, None


def _write_finalization(db, task_id, stage, input_hash, result):
    message = result.get('message') or _message(stage, 'completed')
    result_state = (
        TaskState(result['state']).value
        if result.get('state') is not None
        else None
    )
    next_card = (
        CardId(result['next_card']).value
        if result.get('next_card') is not None
        else None
    )
    checkpoint = dict(result.get('checkpoint') or {})
    checkpoint.update(_event_details(stage, input_hash))
    task = db.get(Task, task_id)
    if task is None:
        raise LookupError('Task not found')
    record_event(db, task_id, 'checkpoint', checkpoint)
    progress = _progress_for(db, task_id)
    progress.stage = stage
    progress.input_hash = input_hash
    progress.message = message
    progress.checkpoint = checkpoint
    progress.traceback = None
    if result_state is not None:
        task.state = result_state
        task.next_card = next_card
    _set_job_status(db, task_id, stage, 'completed')
    completed = _event_details(stage, input_hash)
    completed['message'] = message
    record_event(db, task_id, 'completed', completed)
    db.commit()
    return checkpoint


def _finalize_success(task_id, stage, input_hash, result, session=None):
    if session is not None:
        return _write_finalization(session, task_id, stage, input_hash, result)
    with SessionLocal() as db:
        return _write_finalization(db, task_id, stage, input_hash, result)


def _finalize_success_with_retry(task_id, stage, input_hash, result, session=None, attempts=2):
    last_error = None
    for attempt in range(attempts):
        try:
            return _finalize_success(task_id, stage, input_hash, result, session=session)
        except DBAPIError as error:
            last_error = error
            try:
                if session is not None:
                    session.rollback()
                engine.dispose()
            except Exception:
                pass
            session = None
            _time.sleep(0.5 * (attempt + 1))
    raise last_error


def run_stage(task_id, stage, session_id=None, job_id=None, input_hash=None):
    """Execute a registered stage and persist its recoverable progress."""
    if get_settings().task_store_authority == 'sites':
        from app.remote_stage import run_remote_stage

        return run_remote_stage(
            task_id,
            stage,
            session_id=session_id,
            job_id=job_id,
            input_hash=input_hash,
        )
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise LookupError('Task not found')

        stage_input = _stage_input(db, task_id, stage)
        input_hash = _hash_input(stage_input)
        duplicate, existing_checkpoint = _duplicate_checkpoint(
            db, task_id, stage, input_hash
        )
        if duplicate:
            return existing_checkpoint

        try:
            progress = _progress_for(db, task_id)
            progress.stage = stage
            progress.input_hash = input_hash
            progress.message = _message(stage, 'started')
            progress.checkpoint = None
            progress.traceback = None
            _set_job_status(db, task_id, stage, 'started')
            record_event(db, task_id, 'started', _event_details(stage, input_hash))
            db.commit()

            service = STAGE_SERVICES.get(stage)
            if service is None:
                raise LookupError('No execution service is registered for this stage')
            _consume_stage_quotas(db, task, stage, input_hash)
            result = service(task, stage_input) or {}
            # Checkpoint and completion use a fresh session so a pooled TLS
            # connection that died during the stage can be replaced and retried.
            return _finalize_success_with_retry(task_id, stage, input_hash, result, session=db)
        except StageRateLimitError as error:
            db.rollback()
            message = redact_sensitive_text(error.result.message)
            _record_failure_in_new_session(
                task_id,
                stage,
                input_hash,
                None,
                event_type='rate_limited',
                message=message,
                retry_after=error.result.retry_after,
            )
            public_error = StageExecutionError(message)
        except Exception as error:
            protected = protected_traceback(error)
            retry_after = _provider_retry_after(error)
            db.rollback()
            if retry_after is not None:
                _record_failure_in_new_session(
                    task_id,
                    stage,
                    input_hash,
                    protected,
                    event_type='rate_limited',
                    message=RATE_LIMIT_MESSAGE,
                    retry_after=retry_after,
                )
                public_error = StageExecutionError(RATE_LIMIT_MESSAGE)
            else:
                _record_failure_in_new_session(
                    task_id,
                    stage,
                    input_hash,
                    protected,
                )
                public_error = StageExecutionError(SAFE_FAILURE_MESSAGE)
        # Raise after the handler so the original object is not retained as context.
        raise public_error from None


class QueueAdapter:
    """RQ-backed production queue with an injectable deterministic queue."""

    def __init__(
        self,
        redis_url=None,
        connection=None,
        session_factory=None,
        queue=None,
    ):
        self.connection = connection
        self._session_factory = session_factory
        self.queue = queue
        if self.queue is None:
            if self.connection is None:
                url = redis_url if redis_url is not None else get_settings().redis_url
                if url:
                    self.connection = redis.from_url(url)
            if self.connection is not None:
                self.queue = Queue(QUEUE_NAME, connection=self.connection)

    def enqueue_stage(self, task_id, stage, session_id=None):
        if get_settings().task_store_authority == 'sites':
            from app.remote_stage import enqueue_remote_stage

            return enqueue_remote_stage(self, task_id, stage, session_id)
        factory = self._session_factory or SessionLocal
        with factory() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise LookupError('Task not found')
            input_hash = _hash_input(_stage_input(db, task_id, stage))
            progress = _progress_for(db, task_id)
            progress.stage = stage
            progress.input_hash = input_hash
            progress.message = _message(stage, 'queued')
            progress.checkpoint = None
            progress.traceback = None
            _set_job_status(db, task_id, stage, 'queued')
            record_event(db, task_id, 'queued', _event_details(stage, input_hash))
            db.commit()

        try:
            return self.queue.enqueue(run_stage, task_id, stage)
        except Exception as error:
            protected = protected_traceback(error)
            _record_failure_in_new_session(
                task_id,
                stage,
                input_hash,
                protected,
                session_factory=factory,
                event_type='enqueue_failed',
                message=SAFE_ENQUEUE_MESSAGE,
            )
            public_error = QueueEnqueueError(SAFE_ENQUEUE_MESSAGE)
        raise public_error from None


def worker_status():
    """Report readiness only after an actual Redis PING succeeds."""
    redis_url = get_settings().redis_url
    if not redis_url:
        return 'not_configured'

    connection = None
    try:
        connection = redis.from_url(
            redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        return 'ready' if connection.ping() else 'unavailable'
    except (RedisError, OSError, ValueError):
        return 'unavailable'
    finally:
        if connection is not None:
            try:
                connection.close()
            except (RedisError, OSError):
                pass
