import io
import json
import socket
import traceback
import urllib.error

import pytest

from app.sites_task_store import SitesTaskStoreClient, SitesTaskStoreError
from app.task_store_sync import TaskStoreRevisionConflict, TaskStoreSync


SENSITIVE_BODY = (
    b'token=super-secret-token; SQL=SELECT * FROM private_tasks; '
    b'private-provider-response; /Users/alice/private/task.db'
)
SENSITIVE_FRAGMENTS = (
    'super-secret-token',
    'SELECT * FROM private_tasks',
    'private-provider-response',
    '/Users/alice/private/task.db',
)
QUOTA = {'limit': 2, 'window_seconds': 86400}


class SensitiveBody(io.BytesIO):
    def __init__(self):
        super().__init__(SENSITIVE_BODY)
        self.read_calls = 0

    def read(self, *args, **kwargs):
        self.read_calls += 1
        return super().read(*args, **kwargs)


def make_client(transport):
    return SitesTaskStoreClient(
        origin='https://example.invalid',
        shared_secret='test-only-shared-secret',
        transport=transport,
    )


def sync_state(client):
    return client.sync_task_state(
        task_id='task-1',
        session_id='session-1',
        expected_revision=3,
        state='searching',
        next_card='terms',
    )


def capture_failure(exception_type, call):
    try:
        call()
    except exception_type as error:
        return error, traceback.format_exc()
    pytest.fail('expected %s' % exception_type.__name__)


def assert_no_sensitive_content(error, rendered):
    representations = '\n'.join((str(error), repr(error), rendered))
    assert all(fragment not in representations for fragment in SENSITIVE_FRAGMENTS)


def test_state_write_http_409_is_safe_revision_conflict_without_body_access():
    calls = []
    body = SensitiveBody()
    assert body.getvalue() == SENSITIVE_BODY

    def transport(url, options):
        calls.append((url, options))
        raise urllib.error.HTTPError(url, 409, 'Conflict', hdrs=None, fp=body)

    error, rendered = capture_failure(
        SitesTaskStoreError,
        lambda: sync_state(make_client(transport)),
    )

    assert len(calls) == 1
    assert calls[0][1]['method'] == 'PUT'
    assert error.code == 'revision_conflict'
    assert str(error) == 'revision_conflict'
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True
    assert body.read_calls == 0
    assert_no_sensitive_content(error, rendered)


@pytest.mark.parametrize(
    'status,expected_code',
    [(400, 'task_store_unavailable'), (401, 'session_not_found'), (403, 'worker_unauthorized'),
     (404, 'task_store_unavailable'), (500, 'task_store_unavailable'), (503, 'task_store_unavailable')],
)
def test_other_http_statuses_keep_safe_codes_with_one_call(status, expected_code):
    calls = []
    body = SensitiveBody()

    def transport(url, options):
        calls.append((url, options))
        raise urllib.error.HTTPError(url, status, 'Provider failure', hdrs=None, fp=body)

    error, rendered = capture_failure(
        SitesTaskStoreError,
        lambda: sync_state(make_client(transport)),
    )

    assert len(calls) == 1
    assert error.code == expected_code
    assert error.status == status
    assert str(error) == expected_code
    assert body.read_calls == 0
    assert_no_sensitive_content(error, rendered)


@pytest.mark.parametrize(
    'transport_error',
    [
        TimeoutError('timed out'),
        socket.gaierror(-2, 'Name or service not known'),
        ConnectionError('connection refused'),
    ],
    ids=['timeout', 'dns', 'connection'],
)
def test_network_failures_remain_unavailable_with_one_call(transport_error):
    calls = []

    def transport(url, options):
        calls.append((url, options))
        raise transport_error

    error, rendered = capture_failure(
        SitesTaskStoreError,
        lambda: sync_state(make_client(transport)),
    )

    assert len(calls) == 1
    assert error.code == 'task_store_unavailable'
    assert str(error) == 'task_store_unavailable'
    assert_no_sensitive_content(error, rendered)


def test_non_state_write_http_409_is_skill_version_unavailable():
    calls = []
    body = SensitiveBody()

    def transport(url, options):
        calls.append((url, options))
        raise urllib.error.HTTPError(url, 409, 'Conflict', hdrs=None, fp=body)

    client = make_client(transport)
    error, rendered = capture_failure(
        SitesTaskStoreError,
        lambda: client.create_task(
            session_id='session-1',
            task_id='task-1',
            idempotency_key='request-1',
            skill_version_id='skill-v1',
            quota=QUOTA,
        ),
    )

    assert len(calls) == 1
    assert calls[0][1]['method'] == 'POST'
    assert error.code == 'skill_version_unavailable'
    assert error.status == 409
    assert body.read_calls == 0
    assert_no_sensitive_content(error, rendered)


def test_sync_translates_state_http_409_and_preserves_newer_remote_state():
    calls = []
    body = SensitiveBody()
    expected_revisions = []
    remote = {
        'id': 'task-1',
        'session_id': 'session-1',
        'state': 'collecting_mode',
        'next_card': 'direction',
        'revision': 1,
    }

    def transport(url, options):
        calls.append((url, options))
        if options['method'] == 'GET':
            return {'task': dict(remote)}
        assert options['method'] == 'PUT'
        payload = json.loads(options['body'].decode('utf-8'))
        expected_revisions.append(payload['expected_revision'])
        remote.update(state='done', next_card=None, revision=2)
        raise urllib.error.HTTPError(url, 409, 'Conflict', hdrs=None, fp=body)

    sync = TaskStoreSync(make_client(transport))
    error, rendered = capture_failure(
        TaskStoreRevisionConflict,
        lambda: sync.sync_task_state(
            session_id='session-1',
            task_id='task-1',
            state='searching',
            next_card='terms',
        ),
    )

    assert [options['method'] for _, options in calls] == ['GET', 'PUT']
    assert len(calls) == 2
    assert expected_revisions == [1]
    assert remote == {
        'id': 'task-1',
        'session_id': 'session-1',
        'state': 'done',
        'next_card': None,
        'revision': 2,
    }
    assert error.code == 'revision_conflict'
    assert str(error) == 'revision_conflict'
    assert body.read_calls == 0
    assert_no_sensitive_content(error, rendered)
