import pytest
from fastapi import HTTPException

from app.sites_errors import sites_http_exception
from app.task_store_sync import TaskStoreSyncError


class _UpstreamError(RuntimeError):
    def __init__(self, message, code=None, retry_after=None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if retry_after is not None:
            self.retry_after = retry_after


def _detail(error):
    with pytest.raises(HTTPException) as caught:
        raise sites_http_exception(error)
    return caught.value


def test_allow_listed_code_keeps_status_and_retry_after():
    response = _detail(TaskStoreSyncError('quota_exceeded', retry_after=30))

    assert response.status_code == 429
    assert response.headers['Retry-After'] == '30'
    assert response.detail['code'] == 'quota_exceeded'
    assert response.detail['message'] == 'TaskStoreSyncError: quota_exceeded'


def test_unknown_code_falls_back_to_a_safe_default():
    response = _detail(_UpstreamError('provider said no', code='internal_debug_dump'))

    assert response.status_code == 503
    assert response.detail['code'] == 'task_store_unavailable'


@pytest.mark.parametrize('retry_after', ['30', True, 0, -5, 10 ** 12, '1\r\nX-Injected: 1'])
def test_invalid_retry_after_is_dropped(retry_after):
    response = _detail(TaskStoreSyncError('quota_exceeded', retry_after=retry_after))

    assert 'Retry-After' not in response.headers


def test_message_keeps_type_and_drops_credentials_sql_and_paths():
    response = _detail(_UpstreamError(
        'token=fake-token-4a91 password="fake-password-77c2" '
        'SQL: SELECT * FROM private_table '
        'at /Users/fake/private/task.db'
    ))

    message = response.detail['message']
    assert message.startswith('_UpstreamError: ')
    assert 'fake-token-4a91' not in message
    assert 'fake-password-77c2' not in message
    assert 'SELECT' not in message
    assert '/Users/' not in message


def test_message_is_length_capped():
    response = _detail(_UpstreamError('x' * 5000))

    assert len(response.detail['message']) == 300


@pytest.mark.parametrize(
    ('code', 'status'),
    [
        ('session_not_found', 401),
        ('task_not_found', 404),
        ('job_not_found', 404),
        ('skill_version_unavailable', 409),
        ('revision_conflict', 409),
        ('answer_conflict', 409),
        ('quota_exceeded', 429),
        ('invalid_provider_response', 503),
        ('task_store_unavailable', 503),
        ('worker_unauthorized', 503),
        ('task_store_sync_failed', 503),
    ],
)
def test_every_client_visible_code_keeps_its_http_status(code, status):
    """No code the task-store client emits may be rewritten or re-statused."""
    response = _detail(TaskStoreSyncError(code))

    assert response.status_code == status
    assert response.detail['code'] == code
    assert response.detail['message'] == 'TaskStoreSyncError: {}'.format(code)


def test_allow_list_covers_every_code_the_sync_layer_can_emit():
    from app.sites_errors import SAFE_CODES
    from app.task_store_sync import SAFE_PROVIDER_CODES

    assert SAFE_PROVIDER_CODES <= SAFE_CODES
    assert 'task_store_sync_failed' in SAFE_CODES
    for code in sorted(SAFE_CODES):
        assert _detail(TaskStoreSyncError(code)).detail['code'] == code


def test_provider_local_codes_outside_the_allow_list_are_not_forwarded():
    """sites_task_store emits these internally; _safe_errors already normalises them."""
    for code in ('worker_response_too_large', 'invalid_worker_response'):
        response = _detail(_UpstreamError('boom', code=code))
        assert response.detail['code'] == 'task_store_unavailable'
