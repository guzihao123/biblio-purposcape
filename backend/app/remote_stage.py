"""Authoritative Provider-backed stage execution; no local task/job/progress writes."""

from types import SimpleNamespace
from uuid import uuid4

from app.recovery import protected_traceback
from app.schemas import CardId, TaskState
from app.stage_watchdog import StageWatchdog
from app.task_store_sync import configured_task_store_sync


def _aggregate(sync, task_id, session_id, stage):
    aggregate = sync.get_task_aggregate(session_id, task_id)
    answers = []
    for card in ('direction', 'mode', 'terms', 'years', 'adjustment', 'delivery'):
        if card not in aggregate['answers']:
            continue
        value = aggregate['answers'][card]
        if card == 'direction' and isinstance(value, str):
            value = {'direction': value}
        elif card == 'terms' and isinstance(value, list):
            value = {'terms': value}
        answers.append({'card_id': card, 'value': value})
    return aggregate, {'task_id': task_id, 'stage': stage, 'answers': answers}


def _metadata(sync, task_id, session_id, stage):
    from app.queueing import _hash_input

    aggregate, stage_input = _aggregate(sync, task_id, session_id, stage)
    input_hash = _hash_input(stage_input)
    return aggregate, stage_input, input_hash, f'job-{input_hash[:56]}'


def enqueue_remote_stage(adapter, task_id, stage, session_id):
    from app.queueing import (
        QueueEnqueueError,
        SAFE_ENQUEUE_MESSAGE,
        _message,
        protected_traceback,
        run_stage,
        stage_job_timeout,
    )

    sync = configured_task_store_sync()
    aggregate, stage_input, input_hash, job_id = _metadata(sync, task_id, session_id, stage)
    queued = sync.enqueue_stage(
        session_id=session_id,
        task_id=task_id,
        job_id=job_id,
        stage=stage,
        input_hash=input_hash,
        message=_message(stage, 'queued'),
    )
    if queued['duplicate'] and queued['job']['status'] in {'started', 'completed', 'failed'}:
        return None
    try:
        return adapter.queue.enqueue(
            run_stage,
            task_id,
            stage,
            session_id=session_id,
            job_id=queued['job']['id'],
            input_hash=input_hash,
            job_timeout=stage_job_timeout(),
        )
    except Exception as error:
        protected = protected_traceback(error)
        try:
            sync.fail_stage(
                session_id=session_id,
                task_id=task_id,
                job_id=queued['job']['id'],
                expected_job_revision=queued['job']['revision'],
                lease_token=None,
                event_type='enqueue_failed',
                message=SAFE_ENQUEUE_MESSAGE,
                protected_traceback=protected,
            )
        except Exception:
            pass
        raise QueueEnqueueError(SAFE_ENQUEUE_MESSAGE) from None


def _consume_quotas(sync, task_id, session_id, stage, input_hash):
    from app.queueing import StageRateLimitError
    from app.rate_limit import get_rate_limiter

    operations = {'search': ('retrieval', 'model'), 'generate': ('model',)}.get(stage, ())
    session = sync.get_session_record(session_id)
    source_ip = session.get('client_ip') or 'unknown'
    for operation in operations:
        result = get_rate_limiter().consume(
            operation,
            session_id=session_id,
            source_ip=source_ip,
            idempotency_key=f'{task_id}:{stage}:{input_hash}',
        )
        if not result.allowed:
            raise StageRateLimitError(result)


def _fail_started(sync, task_id, session_id, started, event_type, message, protected, retry_after=None):
    try:
        return sync.fail_stage(
            session_id=session_id,
            task_id=task_id,
            job_id=started['job']['id'],
            expected_job_revision=started['job']['revision'],
            lease_token=started['job']['lease_token'],
            event_type=event_type,
            message=message,
            protected_traceback=protected,
            retry_after=retry_after,
        )
    except Exception:
        return None


def run_remote_stage(task_id, stage, session_id=None, job_id=None, input_hash=None):
    from app.queueing import (
        RATE_LIMIT_MESSAGE,
        SAFE_FAILURE_MESSAGE,
        SAFE_TIMEOUT_MESSAGE,
        STAGE_SERVICES,
        StageExecutionError,
        StageRateLimitError,
        _event_details,
        _message,
        _provider_retry_after,
        protected_traceback,
    )

    sync = configured_task_store_sync()
    if session_id is None:
        raise LookupError('session_id is required for remote stage execution')
    aggregate, stage_input, computed_hash, computed_job = _metadata(sync, task_id, session_id, stage)
    input_hash = input_hash or computed_hash
    job_id = job_id or computed_job
    current = sync.get_stage_job(session_id, task_id, job_id)
    if current['job']['status'] == 'completed':
        return current['progress'].get('checkpoint') or {}
    if current['job']['status'] == 'failed':
        return current['progress'].get('checkpoint') or {}

    expected = current['job']['revision'] if current['job']['status'] == 'queued' else current['job']['revision'] - 1
    started = sync.start_stage(
        session_id=session_id,
        task_id=task_id,
        job_id=job_id,
        expected_job_revision=expected,
        lease_token=str(uuid4()),
        message=_message(stage, 'started'),
    )
    if started['duplicate']:
        return started['progress'].get('checkpoint') or {}

    try:
        _consume_quotas(sync, task_id, session_id, stage, input_hash)
        service = STAGE_SERVICES.get(stage)
        if service is None:
            raise LookupError('No execution service is registered for this stage')
        task = SimpleNamespace(**aggregate)
        # The provider store has no incremental progress action yet, so phase
        # reporting is a no-op here; lifecycle messages stay authoritative.
        from app.progress_reporter import NullReporter, stage_reporting

        def persist_timeout():
            _fail_started(
                sync,
                task_id,
                session_id,
                started,
                'failed',
                SAFE_TIMEOUT_MESSAGE,
                'Stage watchdog hard timeout',
            )

        with stage_reporting(NullReporter()), StageWatchdog(
            stage, task_id, on_timeout=persist_timeout
        ):
            result = service(task, stage_input) or {}
        message = result.get('message') or _message(stage, 'completed')
        result_state = TaskState(result['state']).value if result.get('state') is not None else None
        next_card = CardId(result['next_card']).value if result.get('next_card') is not None else None
        checkpoint = dict(result.get('checkpoint') or {})
        checkpoint.update(_event_details(stage, input_hash))
        completed = sync.complete_stage(
            session_id=session_id,
            task_id=task_id,
            job_id=job_id,
            expected_job_revision=started['job']['revision'],
            lease_token=started['job']['lease_token'],
            state=result_state,
            next_card=next_card,
            message=message,
            checkpoint=checkpoint,
        )
        return completed['checkpoint']
    except StageRateLimitError as error:
        message = error.result.message
        _fail_started(
            sync, task_id, session_id, started, 'rate_limited', message, None,
            retry_after=error.result.retry_after,
        )
        raise StageExecutionError(message) from None
    except Exception as error:
        protected = protected_traceback(error)
        retry_after = _provider_retry_after(error)
        _fail_started(
            sync,
            task_id,
            session_id,
            started,
            'rate_limited' if retry_after is not None else 'failed',
            RATE_LIMIT_MESSAGE if retry_after is not None else SAFE_FAILURE_MESSAGE,
            protected,
            retry_after=retry_after,
        )
        if retry_after is not None:
            raise StageExecutionError(RATE_LIMIT_MESSAGE) from None
        raise StageExecutionError(SAFE_FAILURE_MESSAGE) from None
