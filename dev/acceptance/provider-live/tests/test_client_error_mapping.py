"""Regression: SitesTaskStoreClient must preserve real HTTP statuses and the
fixed safe-code whitelist across the worker boundary, validate session
creation responses, and pass through only validated Retry-After seconds.

These are offline transport-fake tests of the real client code (no injected
client logic): transports here only replay canned HTTPError/JSON, exactly
like the mainline client tests.
"""

import io
import json
import re
import urllib.error

import pytest

import os
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
sys.path.insert(0, BACKEND)

from app.sites_task_store import SitesTaskStoreClient, SitesTaskStoreError  # noqa: E402

SENSITIVE_FRAGMENTS = (
    'super-secret-token',
    'SELECT * FROM private_tasks',
    'private-provider-response',
    '/Users/alice/private/task.db',
)
SENSITIVE_BODY = (
    b'token=super-secret-token; SQL=SELECT * FROM private_tasks; '
    b'private-provider-response; /Users/alice/private/task.db'
)
ROOT = '/functions/v1/app/internal/task-store'


def make_client(transport):
    return SitesTaskStoreClient(
        origin='https://example.invalid',
        shared_secret='test-only-shared-secret',
        transport=transport,
    )


def http_error_transport(status, headers=None):
    calls = []

    def transport(url, options):
        calls.append((url, options))
        raise urllib.error.HTTPError(url, status, 'Provider failure', hdrs=headers, fp=io.BytesIO(SENSITIVE_BODY))

    transport.calls = calls
    return transport


def capture(call):
    with pytest.raises(SitesTaskStoreError) as caught:
        call()
    error = caught.value
    rendered = '\n'.join((str(error), repr(error)))
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in rendered
    return error


def state_write(client):
    return client.sync_task_state(
        task_id='task-1', session_id='session-1',
        expected_revision=1, state='searching', next_card='terms',
    )


def task_create(client):
    return client.create_task(
        session_id='session-1', task_id='task-1', idempotency_key='key-1',
        skill_version_id='skill-1', quota={'limit': 2, 'window_seconds': 3600},
    )


def test_state_write_409_is_revision_conflict_with_status():
    client = make_client(http_error_transport(409))
    error = capture(lambda: state_write(client))
    assert error.code == 'revision_conflict'
    assert error.status == 409
    assert error.retry_after is None


def test_task_create_409_is_skill_version_unavailable_with_status():
    client = make_client(http_error_transport(409))
    error = capture(lambda: task_create(client))
    assert error.code == 'skill_version_unavailable'
    assert error.status == 409


def test_task_create_429_is_quota_exceeded_with_validated_retry_after():
    headers = {'Retry-After': '30'}
    client = make_client(http_error_transport(429, headers=headers))
    error = capture(lambda: task_create(client))
    assert error.code == 'quota_exceeded'
    assert error.status == 429
    assert error.retry_after == 30


@pytest.mark.parametrize('header_value', ['abc', '-5', '30.5', '  ', '999999999999999999999', '30; url=x'])
def test_task_create_429_rejects_unvalidated_retry_after(header_value):
    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)
    client = make_client(http_error_transport(429, headers=Headers({'Retry-After': header_value})))
    error = capture(lambda: task_create(client))
    assert error.code == 'quota_exceeded'
    assert error.retry_after is None


def test_401_is_session_not_found_and_403_is_worker_unauthorized():
    error = capture(lambda: task_create(make_client(http_error_transport(401))))
    assert error.code == 'session_not_found'
    assert error.status == 401
    error = capture(lambda: task_create(make_client(http_error_transport(403))))
    assert error.code == 'worker_unauthorized'
    assert error.status == 403


@pytest.mark.parametrize('status', [400, 404, 405, 413, 500, 502, 503])
def test_unlisted_statuses_stay_task_store_unavailable_with_status(status):
    error = capture(lambda: task_create(make_client(http_error_transport(status))))
    assert error.code == 'task_store_unavailable'
    assert error.status == status


@pytest.mark.parametrize('status,expected', [(429, 'task_store_unavailable'), (401, 'session_not_found'), (403, 'worker_unauthorized')])
def test_status_only_codes_do_not_apply_to_state_write_path(status, expected):
    # revision_conflict is reserved for the state-write 409; 401/403 keep
    # their identity codes on every fixed path, while 429 stays quota-specific
    # to task creation and never attaches retry_after elsewhere.
    if status == 429:
        client = make_client(http_error_transport(429, headers={'Retry-After': '7'}))
        error = capture(lambda: state_write(client))
        assert error.code == 'task_store_unavailable'
        assert error.retry_after is None
    else:
        error = capture(lambda: state_write(make_client(http_error_transport(status))))
        assert error.code == expected
        assert error.status == status


@pytest.mark.parametrize('returned', [
    {},
    {'id': ''},
    {'id': 123},
    {'id': None},
    {'id': 'has space'},
    {'id': 'x' * 65},
    {'id': '../escape'},
    {'id': 'ok-id', 'extra': 'ignored'},
])
def test_create_anonymous_session_validates_returned_id(returned):
    def transport(url, options):
        assert url.endswith('/sessions')
        assert json.loads(options['body'].decode('utf-8'))['id'] == 'wanted-id'
        return dict(returned)

    client = make_client(transport)
    if returned.get('id') == 'ok-id':
        assert client.create_anonymous_session(session_id='wanted-id') == 'ok-id'
    else:
        error = capture(lambda: client.create_anonymous_session(session_id='wanted-id'))
        assert error.code == 'invalid_worker_response'


def test_create_anonymous_session_without_id_omits_payload_field():
    seen = {}

    def transport(url, options):
        seen['body'] = json.loads(options['body'].decode('utf-8'))
        return {'id': 'generated-session'}

    client = make_client(transport)
    assert client.create_anonymous_session() == 'generated-session'
    assert 'id' not in seen['body']


def test_error_repr_remains_safe_with_new_fields():
    error = SitesTaskStoreError('quota_exceeded', status=429, retry_after=30)
    rendered = '\n'.join((str(error), repr(error)))
    assert rendered == 'quota_exceeded\nSitesTaskStoreError(\'quota_exceeded\')'
    assert '30' not in repr(error)


@pytest.mark.parametrize('method_name,value', [
    ('answer_direction', 'direction'),
    ('answer_mode', 'A'),
    ('answer_terms', ['term']),
    ('answer_years', {'choice': 'B'}),
    ('answer_adjustment', {'adjustment': ['continue']}),
    ('answer_delivery', {'form': 'B'}),
])
@pytest.mark.parametrize('status,expected', [
    (409, 'revision_conflict'),
    (422, 'answer_conflict'),
])
def test_every_card_answer_preserves_conflict_codes(method_name, value, status, expected):
    client = make_client(http_error_transport(status))
    method = getattr(client, method_name)
    error = capture(lambda: method('task-1', 'session-1', 8, value))
    assert error.code == expected
    assert error.status == status


def test_stage_write_409_is_revision_conflict_and_job_404_is_specific():
    conflict_client = make_client(http_error_transport(409))
    error = capture(lambda: conflict_client.complete_stage(
        'task-1', 'session-1', 'job-1', 2, 'lease-1',
        'dashboard_ready', 'adjustment', 'done', {'stage': 'search'},
    ))
    assert error.code == 'revision_conflict'
    assert error.status == 409

    missing_client = make_client(http_error_transport(404))
    error = capture(lambda: missing_client.get_stage_job('task-1', 'session-1', 'job-1'))
    assert error.code == 'job_not_found'
    assert error.status == 404
