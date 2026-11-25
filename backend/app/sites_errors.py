"""Client-safe translation of Qoder Sites task-store failures.

Upstream failures can carry provider URLs, credentials, SQL, or response bodies
in ``str(error)``. Only an allow-listed error code and a redacted, length-capped
diagnostic may cross the HTTP boundary.
"""

from fastapi import HTTPException

from app.recovery import redact_sensitive_text
from app.task_store_sync import SAFE_PROVIDER_CODES

STATUS_BY_CODE = {
    'session_not_found': 401,
    'skill_version_unavailable': 409,
    'quota_exceeded': 429,
    'revision_conflict': 409,
    'answer_conflict': 409,
    'task_not_found': 404,
    'job_not_found': 404,
    'invalid_provider_response': 503,
}
DEFAULT_CODE = 'task_store_unavailable'
DEFAULT_STATUS = 503
# Codes the sync layer may emit in addition to the provider allow-list.
EXTRA_SAFE_CODES = frozenset({'task_store_sync_failed'})
SAFE_CODES = SAFE_PROVIDER_CODES | EXTRA_SAFE_CODES
MAX_MESSAGE_LENGTH = 300
MAX_RETRY_AFTER = 999_999_999


def safe_code(error):
    code = getattr(error, 'code', DEFAULT_CODE)
    if not isinstance(code, str) or code not in SAFE_CODES:
        return DEFAULT_CODE
    return code


def safe_retry_after(error):
    retry_after = getattr(error, 'retry_after', None)
    if isinstance(retry_after, bool) or not isinstance(retry_after, int):
        return None
    if not 1 <= retry_after <= MAX_RETRY_AFTER:
        return None
    return retry_after


def safe_message(error, code):
    """Keep the exception type and redacted text so operators can still diagnose."""
    rendered = '{}: {}'.format(type(error).__name__, error)
    redacted = redact_sensitive_text(rendered) or code
    return redacted[:MAX_MESSAGE_LENGTH]


def sites_http_exception(error):
    code = safe_code(error)
    retry_after = safe_retry_after(error)
    headers = {'Retry-After': str(retry_after)} if retry_after else {}
    return HTTPException(
        status_code=STATUS_BY_CODE.get(code, DEFAULT_STATUS),
        detail={'code': code, 'message': safe_message(error, code)},
        headers=headers,
    )
