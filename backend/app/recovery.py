import json
import logging
import os
import random
import re
import time
import traceback
from datetime import datetime, timezone
from urllib.error import URLError

import redis.exceptions

try:
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
except ImportError:
    _OPENAI_TRANSIENT_ERRORS = ()
else:
    _OPENAI_TRANSIENT_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

from app.db import SessionLocal
from app.models import Task, TaskEvent, TaskJob, TaskProgress
from app.rate_limit import get_rate_limiter
from app.schemas import CardId, TaskState
from app.task_expiry import expire_idle_collection_tasks


_REDACTED = '[REDACTED]'
_REDACTED_PATH = '[REDACTED_PATH]'
_REDACTED_SQL = '[REDACTED_SQL]'
_REDACTED_PROVIDER_BODY = '[REDACTED_PROVIDER_BODY]'
_SAFETY_MARKER_RE = re.compile(
    r'\b(?:OFFLINE_[A-Z0-9_]+|[A-Z][A-Z0-9_]*_FORCED_[A-Z0-9_]+)\b'
)
_PROVIDER_BODY_RE = re.compile(
    r'\b(?:provider\s+response(?:\s+body)?|provider\s+body|response[_\s-]*body)'
    r'\s*[:=]\s*',
    re.IGNORECASE,
)
_SQL_LABEL_RE = re.compile(r'\bSQL\s*[:=]\s*[^\n]*', re.IGNORECASE)
_SQL_STATEMENT_RE = re.compile(
    r'\b(?:SELECT\s+[^\n]*|INSERT\s+INTO\s+[^\n]*|UPDATE\s+\S+\s+SET\s+[^\n]*|'
    r'DELETE\s+FROM\s+[^\n]*|CREATE\s+(?:TABLE|INDEX)\s+[^\n]*|'
    r'ALTER\s+TABLE\s+[^\n]*|DROP\s+TABLE\s+[^\n]*)',
    re.IGNORECASE,
)
_SQL_PARAMETERS_RE = re.compile(r'\[parameters\]\s*:[^\n]*', re.IGNORECASE)
_URL_CREDENTIALS_RE = re.compile(
    r'(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)[^\s/@]+@'
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r'(?P<prefix>\b(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|'
    r'password|passwd|pwd|client[_-]?secret|refresh[_-]?token|authorization|'
    r'credentials?|signature)\b[\"\']?\s*[:=]\s*)'
    r'(?P<value>\"(?:\\.|[^\"\\])*\"|\'(?:\\.|[^\'\\])*\'|'
    r'Bearer\s+[^\s,;}\]]+|[^\s,;}\]]+)',
    re.IGNORECASE,
)
_UNIX_PATH_RE = re.compile(
    r'(?<![\w:/])/(?:[^\s/:*?"<>|]+/)*[^\s/:*?"<>|]+'
)
_WINDOWS_PATH_RE = re.compile(
    r'(?i)(?<!\w)(?:[a-z]:[\\/]|\\\\)[^\s"\'<>|]*'
)
# Environment values are only replaced when the name or the value itself marks a
# credential. Replacing every value (or every long value) also destroys ordinary
# diagnostics such as IP addresses, "HTTP/1.1", or the word "cat" from PAGER.
_ENV_SECRET_NAME_RE = re.compile(
    r'api[_-]?key|access[_-]?key|secret|private[_-]?key|password|passwd|token|'
    r'credential|auth[_-]?key|signing[_-]?key',
    re.IGNORECASE,
)
_ENV_KEY_SUFFIX_RE = re.compile(r'(?:^|_)key$', re.IGNORECASE)
_ENV_NON_SECRET_VALUE_RE = re.compile(
    r'\A(?:\d+|true|false|yes|no|on|off|none|null|nil|auto|default|debug|info|'
    r'warn|warning|error|critical|trace|fatal|[A-Za-z]{1,3})\Z',
    re.IGNORECASE,
)
_CREDENTIAL_VALUE_RE = re.compile(
    r'(?<![A-Za-z0-9])(?:'
    r'sk-[A-Za-z0-9_-]{8,}|sk_(?:live|test)_[A-Za-z0-9]{8,}|'
    r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|'
    r'xox[abprs]-[A-Za-z0-9-]{8,}|(?:AKIA|ASIA)[0-9A-Z]{16}|'
    r'AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.'
    r')'
)


def _protect_safety_markers(text):
    markers = []

    def protect(match):
        markers.append(match.group(0))
        # Unique private-use characters cannot overlap or be damaged by env values.
        return chr(0xE000 + len(markers) - 1)

    return _SAFETY_MARKER_RE.sub(protect, text), markers


def _restore_safety_markers(text, markers):
    for index, marker in enumerate(markers):
        text = text.replace(chr(0xE000 + index), marker)
    return text


def _redact_provider_bodies(text):
    decoder = json.JSONDecoder()
    pieces = []
    position = 0
    for match in _PROVIDER_BODY_RE.finditer(text):
        pieces.append(text[position:match.end()])
        body_start = match.end()
        json_start = body_start
        while json_start < len(text) and text[json_start].isspace():
            json_start += 1
        body_end = text.find('\n', body_start)
        if body_end < 0:
            body_end = len(text)
        try:
            _, json_end = decoder.raw_decode(text, json_start)
        except (ValueError, TypeError):
            pass
        else:
            body_end = json_end
        pieces.append(_REDACTED_PROVIDER_BODY)
        position = body_end
    pieces.append(text[position:])
    return ''.join(pieces)


def _is_credential_env_value(name, value):
    """Decide whether one environment value is a credential worth replacing."""
    if not value:
        return False
    if _CREDENTIAL_VALUE_RE.search(value):
        return True
    if _ENV_SECRET_NAME_RE.search(name):
        # Flag-style values (ENABLE_*_TOKEN=1, *_TOKEN_BUDGET=4096) are settings,
        # not credentials; replacing them corrupts unrelated numbers in logs.
        return len(value) >= 6 and not _ENV_NON_SECRET_VALUE_RE.match(value)
    if _ENV_KEY_SUFFIX_RE.search(name):
        return (
            len(value) >= 16
            and not re.search(r'\s', value)
            and re.search(r'[A-Za-z]', value) is not None
            and re.search(r'\d', value) is not None
            and not _ENV_NON_SECRET_VALUE_RE.match(value)
        )
    return False


def redact_sensitive_text(value, environ=None):
    """Redact secrets while retaining safe exception types and test markers."""
    if value is None:
        return None
    text = str(value)
    text, markers = _protect_safety_markers(text)
    text = _redact_provider_bodies(text)
    text = _SQL_LABEL_RE.sub(_REDACTED_SQL, text)
    text = _SQL_STATEMENT_RE.sub(_REDACTED_SQL, text)
    text = _SQL_PARAMETERS_RE.sub('[parameters: [REDACTED]]', text)
    text = _URL_CREDENTIALS_RE.sub(
        lambda match: match.group('scheme') + '[REDACTED_CREDENTIALS]@',
        text,
    )
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: match.group('prefix') + _REDACTED,
        text,
    )
    text = _WINDOWS_PATH_RE.sub(_REDACTED_PATH, text)
    text = _UNIX_PATH_RE.sub(_REDACTED_PATH, text)
    values = {
        item
        for name, item in (os.environ if environ is None else environ).items()
        if _is_credential_env_value(name, item)
    }
    for item in sorted(values, key=len, reverse=True):
        text = text.replace(item, '[REDACTED_ENV]')
    return _restore_safety_markers(text, markers)


def protected_traceback(error):
    """Format only the current failure, never its raw cause/context chain."""
    rendered = ''.join(traceback.format_exception(
        type(error),
        error,
        error.__traceback__,
        chain=False,
    ))
    return redact_sensitive_text(rendered)


class WorkerLogRedactionFilter(logging.Filter):
    """Sanitize RQ records before any attached handler formats them."""

    def filter(self, record):
        try:
            message = record.getMessage()
            if record.exc_info:
                message += '\n' + ''.join(traceback.format_exception(
                    *record.exc_info,
                    chain=False,
                ))
            record.msg = redact_sensitive_text(message)
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        except Exception:
            record.msg = 'Worker log details suppressed by redaction.'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def _redact_access_target(value):
    text = str(value)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: match.group('prefix') + _REDACTED,
        text,
    )
    text = re.sub(
        r'(?P<prefix>/api/(?:tasks|admin/sessions)/)[^/?\s]+',
        lambda match: match.group('prefix') + _REDACTED,
        text,
    )
    return re.sub(
        r'(?P<prefix>/artifacts/)[^?#\s]+',
        lambda match: match.group('prefix') + _REDACTED_PATH,
        text,
    )


class UvicornAccessLogRedactionFilter(logging.Filter):
    def filter(self, record):
        try:
            client_addr, method, full_path, http_version, status_code = record.args
            record.args = (
                redact_sensitive_text(client_addr),
                redact_sensitive_text(method),
                _redact_access_target(full_path),
                redact_sensitive_text(http_version),
                status_code,
            )
            record.exc_info = None
            record.exc_text = None
        except Exception:
            record.msg = 'Access log details suppressed by redaction.'
            record.args = ('', '', '[REDACTED_PATH]', '', 0)
            record.exc_info = None
            record.exc_text = None
        return True


def install_worker_log_redaction():
    filter_types = (
        ('rq', WorkerLogRedactionFilter),
        ('rq.worker', WorkerLogRedactionFilter),
        ('rq.job', WorkerLogRedactionFilter),
        ('uvicorn.access', UvicornAccessLogRedactionFilter),
        ('uvicorn.error', WorkerLogRedactionFilter),
    )
    for name, filter_type in filter_types:
        logger = logging.getLogger(name)
        if not any(getattr(item, '_landscape_redaction', False) for item in logger.filters):
            redaction = filter_type()
            redaction._landscape_redaction = True
            logger.addFilter(redaction)


TRANSIENT_ERRORS = (
    TimeoutError, ConnectionError, URLError, redis.exceptions.RedisError,
) + _OPENAI_TRANSIENT_ERRORS


class QuotaExceeded(RuntimeError):
    def __init__(self, result):
        self.result = result
        self.retry_after = result.retry_after
        super().__init__(result.message)


def enforce_quota(operation, session_id, source_ip, idempotency_key, limiter=None):
    limiter = limiter or get_rate_limiter()
    result = limiter.consume(
        operation,
        session_id=session_id,
        source_ip=source_ip,
        idempotency_key=idempotency_key,
    )
    if not result.allowed:
        raise QuotaExceeded(result)
    return result


def retry_call(call, attempts=3, base_delay=0.2, max_delay=2.0, jitter=0.1, sleep=time.sleep):
    if attempts < 1:
        raise ValueError('attempts must be positive')
    for attempt in range(attempts):
        try:
            return call()
        except TRANSIENT_ERRORS:
            if attempt == attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            if jitter:
                delay *= 1 + random.uniform(-jitter, jitter)
            sleep(max(0, delay))


def _now(now):
    return now() if now is not None else datetime.now(timezone.utc)


def _seconds(now, then):
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, int((now - then).total_seconds()))


def recover_interrupted_tasks(
    session_factory=SessionLocal,
    stale_after=None,
    now=None,
    enqueue=None,
):
    del enqueue
    current = _now(now)
    if stale_after is None:
        stale_after = int(os.environ.get('STAGE_STALE_SECONDS', '1800'))
    results = []
    with session_factory() as db:
        jobs = db.query(TaskJob).filter_by(status='started').all()
        for job in jobs:
            progress = db.get(TaskProgress, job.task_id)
            if progress is None or progress.updated_at is None:
                continue
            if _seconds(current, progress.updated_at) < stale_after:
                continue
            task = db.get(Task, job.task_id)
            if task is None:
                continue
            checkpoint = progress.checkpoint or {}
            stage = checkpoint.get('stage') or job.kind
            if checkpoint and stage in {'search', 'generate'}:
                if stage == 'search':
                    task.state = TaskState.DASHBOARD_READY.value
                    task.next_card = CardId.ADJUSTMENT.value
                else:
                    task.state = TaskState.DONE.value
                    task.next_card = None
                job.status = 'completed'
                progress.message = '已从检查点恢复，未重复执行检索或模型调用'
                progress.percent = 100
                action = 'settled_checkpoint'
                event_type = 'recovered'
            else:
                task.state = TaskState.ERROR.value
                job.status = 'interrupted'
                progress.message = '执行中断，外部服务结果未确认，请人工复核后重试'
                progress.percent = 0
                action = 'manual_review'
                event_type = 'recovery_manual_required'
            db.add(TaskEvent(
                task_id=task.id,
                event_type=event_type,
                payload={
                    'stage': stage,
                    'resumed_from': stage,
                    'action': action,
                    'duplicate_searches': 0,
                    'timestamp': current.isoformat(),
                },
            ))
            results.append({
                'task_id': task.id,
                'resumed_from': stage,
                'action': action,
                'duplicate_searches': 0,
            })
        db.commit()
    return results


def schedule_due_retries(
    session_factory=SessionLocal,
    now=None,
    enqueue=None,
    max_attempts=3,
):
    current = _now(now)
    if enqueue is None:
        from app.queueing import QueueAdapter
        enqueue = lambda task_id, stage, delay: QueueAdapter().enqueue_stage(task_id, stage)

    results = []
    with session_factory() as db:
        jobs = db.query(TaskJob).filter_by(status='failed').all()
        for job in jobs:
            progress = db.get(TaskProgress, job.task_id)
            if progress is None or progress.updated_at is None:
                continue
            events = db.query(TaskEvent).filter_by(
                task_id=job.task_id,
                event_type='rate_limited',
            ).order_by(TaskEvent.id).all()
            if not events:
                continue
            if len(events) >= max_attempts:
                db.add(TaskEvent(
                    task_id=job.task_id,
                    event_type='retry_exhausted',
                    payload={'stage': job.kind, 'attempts': len(events)},
                ))
                continue
            latest = events[-1]
            retry_after = int(latest.payload.get('retry_after') or 60)
            elapsed = _seconds(current, progress.updated_at)
            if elapsed < retry_after:
                continue
            delay = max(0, retry_after - elapsed)
            task = db.get(Task, job.task_id)
            if task is None:
                continue
            job.status = 'queued'
            task.state = TaskState.SEARCHING.value if job.kind == 'search' else TaskState.GENERATING.value
            task.next_card = None
            progress.message = '等待延迟重试' if delay else '准备重试'
            progress.percent = 0
            db.add(TaskEvent(
                task_id=job.task_id,
                event_type='retry_scheduled',
                payload={'stage': job.kind, 'delay_seconds': delay, 'attempt': len(events) + 1},
            ))
            db.flush()
            enqueue(task.id, job.kind, delay)
            results.append({'task_id': task.id, 'action': 'requeued', 'delay_seconds': delay})
        db.commit()
    return results


def run_recovery_cycle(now=None, enqueue=None, session_factory=SessionLocal):
    from app.config import get_settings

    expired = expire_idle_collection_tasks(
        now=now,
        session_factory=session_factory,
    )
    if get_settings().task_store_authority == 'sites':
        from app.remote_recovery import run_remote_recovery_cycle

        result = run_remote_recovery_cycle(now=now)
        result['expired'] = expired
        return result
    return {
        'recovered': recover_interrupted_tasks(
            now=now, enqueue=enqueue, session_factory=session_factory,
        ),
        'requeued': schedule_due_retries(
            now=now, enqueue=enqueue, session_factory=session_factory,
        ),
        'expired': expired,
    }


def start_recovery_scheduler(interval=60):
    from threading import Thread

    def loop():
        while True:
            try:
                run_recovery_cycle()
            except Exception:
                pass
            time.sleep(interval)

    thread = Thread(target=loop, name='landscape-recovery', daemon=True)
    thread.start()
    return thread
