from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.rate_limit import RateLimitResult
from app.security import require_session
from app.task_store_sync import TaskStoreSyncError


def remote_task(**overrides):
    task = {
        'id': 'task-1',
        'session_id': 'owner-1',
        'skill_version_id': 'skill-1',
        'state': 'collecting_mode',
        'next_card': 'direction',
        'revision': 1,
        'created_at': '2026-11-25T00:00:00Z',
        'updated_at': '2026-11-25T00:00:00Z',
        'answers': {},
        'progress': {'stage': 'collecting', 'message': '', 'checkpoint': None},
    }
    task.update(overrides)
    return task


class FakeSitesSync:
    def __init__(self):
        self.task = remote_task()
        self.terms_event = None
        self.calls = []
        self.failure = None

    def _maybe_fail(self):
        if self.failure is not None:
            raise self.failure

    def get_published_skill(self):
        self._maybe_fail()
        return {'id': 'skill-1', 'version': 1, 'state': 'published'}

    def create_task(self, **kwargs):
        self._maybe_fail()
        self.calls.append(('create_task', kwargs))
        self.task.update(id=kwargs['task_id'], state='collecting_mode', next_card='direction')
        return dict(self.task)

    def list_tasks(self, session_id):
        return [dict(self.task)]

    def get_task(self, session_id, task_id):
        return dict(self.task)

    def get_task_aggregate(self, session_id, task_id):
        return dict(self.task)

    def answer_card(self, session_id, task_id, card_id, value):
        self.calls.append(('answer_card', card_id, value))
        self.task['answers'][card_id] = value
        self.task['revision'] += 1
        if card_id == 'mode':
            self.task.update(state='collecting_terms', next_card='terms')
        elif card_id == 'years':
            self.task.update(state='searching', next_card=None)
        return {'task': dict(self.task), 'changed': True}

    def get_latest_terms_event(self, session_id, task_id):
        return self.terms_event

    def get_skill_version(self, session_id, skill_version_id):
        return {'id': skill_version_id, 'version': 1, 'state': 'published', 'content': {}}

    def append_task_event(self, session_id, task_id, event_type, event_key, payload):
        self.terms_event = {
            'task_id': task_id, 'event_type': event_type,
            'event_key': event_key, 'payload': payload,
        }
        self.calls.append(('append_task_event', event_type))
        return self.terms_event


class AllowAllLimiter:
    def source_ip(self, request):
        return '203.0.113.10'

    def consume(self, *args, **kwargs):
        return RateLimitResult(allowed=True)


class FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue_stage(self, task_id, stage, session_id=None):
        self.calls.append((task_id, stage, session_id))


@pytest.fixture
def sites_client(monkeypatch):
    sync = FakeSitesSync()
    queue = FakeQueue()
    monkeypatch.setenv('TASK_STORE_AUTHORITY', 'sites')
    get_settings.cache_clear()
    monkeypatch.setattr('app.main._sites_sync', lambda: sync)
    monkeypatch.setattr('app.main.queue_adapter', queue)
    monkeypatch.setattr('app.main.candidate_service.generate', lambda direction, mode: [
        {'value': 'term-a', 'label': 'term-a', 'description': 'd', 'preview': 'p'},
    ])
    app.dependency_overrides[require_session] = lambda: SimpleNamespace(id='owner-1')
    app.dependency_overrides[
        __import__('app.rate_limit', fromlist=['get_rate_limiter']).get_rate_limiter
    ] = lambda: AllowAllLimiter()
    client = TestClient(app, base_url='https://testserver')
    try:
        yield client, sync, queue
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_sites_create_list_and_read_use_remote_store(sites_client):
    client, sync, _ = sites_client
    created = client.post('/api/tasks', headers={'Idempotency-Key': 'key-1'})
    assert created.status_code == 201
    assert created.json()['id'] == sync.task['id']
    assert sync.calls[0][0] == 'create_task'

    listed = client.get('/api/tasks')
    assert listed.status_code == 200
    assert [task['id'] for task in listed.json()['tasks']] == [sync.task['id']]

    read = client.get(f"/api/tasks/{sync.task['id']}")
    assert read.status_code == 200
    assert read.json()['state'] == 'collecting_mode'


def test_sites_mode_answer_prepares_remote_terms_candidates(sites_client):
    client, sync, _ = sites_client
    response = client.post(
        f"/api/tasks/{sync.task['id']}/answers/mode",
        json={'value': {'mode': 'A'}},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['next_card'] == 'terms'
    assert payload['card']['id'] == 'terms'
    assert any(call[0] == 'append_task_event' for call in sync.calls)


def test_sites_years_answer_enqueues_remote_stage(sites_client):
    client, sync, queue = sites_client
    sync.task.update(state='collecting_years', next_card='years', revision=4)
    response = client.post(
        f"/api/tasks/{sync.task['id']}/answers/years",
        json={'value': {'choice': 'B'}},
    )
    assert response.status_code == 200, response.text
    assert queue.calls == [(sync.task['id'], 'search', 'owner-1')]


def test_sites_quota_error_maps_to_429(sites_client):
    client, sync, _ = sites_client
    sync.failure = TaskStoreSyncError('quota_exceeded', retry_after=30)
    response = client.post('/api/tasks', headers={'Idempotency-Key': 'key-quota'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '30'
    assert response.json()['detail']['code'] == 'quota_exceeded'

def test_sites_upstream_error_text_is_redacted_but_still_diagnosable(sites_client):
    client, sync, _ = sites_client
    api_key = 'sk-live-8f3a91c2d4b5e6071a2b'
    db_password = 'fake-db-password-91c4'
    sync.failure = RuntimeError(
        'upstream 502 while calling https://sites.internal/api/v1/tasks '
        f'(api_key={api_key}, password={db_password})'
    )

    response = client.post('/api/tasks', headers={'Idempotency-Key': 'key-secret'})

    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['code'] == 'task_store_unavailable'
    message = detail['message']
    assert api_key not in message
    assert db_password not in message
    assert '[REDACTED]' in message
    assert 'RuntimeError' in message
    assert 'upstream 502' in message
    assert len(message) <= 300


def test_sites_error_code_outside_the_allow_list_is_not_echoed(sites_client):
    client, sync, _ = sites_client

    class UnsafeStoreError(RuntimeError):
        code = 'sk-live-code-should-never-surface'

    sync.failure = UnsafeStoreError('provider rejected the request')

    response = client.post('/api/tasks', headers={'Idempotency-Key': 'key-code'})

    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['code'] == 'task_store_unavailable'
    assert 'sk-live-code-should-never-surface' not in response.text
