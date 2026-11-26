from types import SimpleNamespace

import fakeredis
import httpx
import openai
import pytest

from app.config import get_settings
from app.queueing import (
    QueueAdapter,
    QueueEnqueueError,
    STAGE_SERVICES,
    StageExecutionError,
    run_stage,
)
from app.rate_limit import RATE_LIMIT_MESSAGE, RateLimiter
from app.schemas import TaskState


class FakeRemoteSync:
    def __init__(self):
        self.task = {
            'id': 'task-1', 'session_id': 'owner-1', 'skill_version_id': 'skill-1',
            'state': 'searching', 'next_card': None, 'revision': 5,
            'answers': {
                'direction': 'topic', 'mode': {'mode': 'A'},
                'terms': ['term'], 'years': {'choice': 'B'},
            },
        }
        self.job = {
            'id': 'job-test', 'task_id': 'task-1', 'stage': 'search',
            'input_hash': 'a' * 64, 'status': 'queued', 'attempt': 0,
            'revision': 1, 'task_revision': 5, 'lease_token': None,
            'next_retry_at': None,
        }
        self.progress = {'checkpoint': None}
        self.events = []
        self.service_calls = []
        self.failures = []

    def get_task_aggregate(self, session_id, task_id):
        return dict(self.task)

    def get_session_record(self, session_id):
        return {'id': session_id, 'client_ip': '203.0.113.10'}

    def get_stage_job(self, session_id, task_id, job_id):
        return self._result(duplicate=False)

    def start_stage(self, **kwargs):
        assert kwargs['expected_job_revision'] == 1
        self.job.update(
            status='started', attempt=1, revision=2,
            lease_token=kwargs['lease_token'],
        )
        self.events.append('started')
        return self._result(duplicate=False)

    def complete_stage(self, **kwargs):
        self.job.update(status='completed', revision=3, lease_token=None)
        self.task.update(state=kwargs['state'], next_card=kwargs['next_card'], revision=6)
        self.progress['checkpoint'] = kwargs['checkpoint']
        self.events.extend(['checkpoint', 'completed'])
        return dict(self._result(duplicate=False), checkpoint=kwargs['checkpoint'])

    def fail_stage(self, **kwargs):
        self.failures.append(kwargs)
        self.job.update(status='failed', revision=3, lease_token=None, next_retry_at='later')
        self.task['state'] = 'error'
        self.events.append(kwargs['event_type'])
        return self._result(duplicate=False)

    def enqueue_stage(self, **kwargs):
        self.queued = kwargs
        return self._result(duplicate=False)

    def _result(self, duplicate):
        return {
            'job': dict(self.job), 'task': dict(self.task),
            'progress': dict(self.progress), 'events': [], 'duplicate': duplicate,
        }


@pytest.fixture(autouse=True)
def configure_sites(monkeypatch):
    monkeypatch.setenv('TASK_STORE_AUTHORITY', 'sites')
    get_settings.cache_clear()
    monkeypatch.setattr(
        'app.queueing.SessionLocal',
        lambda: (_ for _ in ()).throw(AssertionError('local database forbidden')),
    )
    monkeypatch.setattr(
        'app.queueing.get_rate_limiter',
        lambda: RateLimiter(connection=fakeredis.FakeRedis()),
    )
    monkeypatch.setattr(
        'app.rate_limit.get_rate_limiter',
        lambda: RateLimiter(connection=fakeredis.FakeRedis()),
    )
    yield
    get_settings.cache_clear()
    STAGE_SERVICES.clear()


def test_remote_success_never_opens_local_database(monkeypatch):
    remote = FakeRemoteSync()
    monkeypatch.setattr('app.remote_stage.configured_task_store_sync', lambda: remote)

    def service(task, stage_input):
        remote.service_calls.append((task, stage_input))
        return {
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': 'adjustment',
            'message': 'done',
            'checkpoint': {'stage': 'search'},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', service)
    checkpoint = run_stage(
        'task-1', 'search', session_id='owner-1', job_id='job-test', input_hash='a' * 64,
    )
    assert checkpoint['stage'] == 'search'
    assert checkpoint['input_hash'] == 'a' * 64
    assert len(remote.service_calls) == 1
    assert remote.events == ['started', 'checkpoint', 'completed']


def test_remote_stage_wraps_service_with_watchdog(monkeypatch):
    remote = FakeRemoteSync()
    monkeypatch.setattr('app.remote_stage.configured_task_store_sync', lambda: remote)
    events = []

    class RecordingWatchdog:
        def __init__(self, stage, task_id, **kwargs):
            events.append(('init', stage, task_id, callable(kwargs.get('on_timeout'))))

        def __enter__(self):
            events.append(('enter',))

        def __exit__(self, exc_type, exc, traceback):
            events.append(('exit', exc_type.__name__ if exc_type else None))
            return False

    monkeypatch.setattr('app.remote_stage.StageWatchdog', RecordingWatchdog)

    def service(task, stage_input):
        events.append(('service',))
        return {
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': 'adjustment',
            'message': 'done',
            'checkpoint': {'stage': 'search'},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', service)
    run_stage(
        'task-1', 'search', session_id='owner-1', job_id='job-test', input_hash='a' * 64,
    )

    assert events == [
        ('init', 'search', 'task-1', True),
        ('enter',),
        ('service',),
        ('exit', None),
    ]


def test_remote_completed_duplicate_only_returns_checkpoint(monkeypatch):
    remote = FakeRemoteSync()
    remote.job.update(status='completed', revision=3)
    remote.progress['checkpoint'] = {'stage': 'search', 'clean': True}
    monkeypatch.setattr('app.remote_stage.configured_task_store_sync', lambda: remote)
    monkeypatch.setitem(
        STAGE_SERVICES,
        'search',
        lambda *args: (_ for _ in ()).throw(AssertionError('duplicate service call')),
    )

    checkpoint = run_stage(
        'task-1', 'search', session_id='owner-1', job_id='job-test', input_hash='a' * 64,
    )
    assert checkpoint == {'stage': 'search', 'clean': True}
    assert remote.events == []


def test_remote_provider_429_uses_safe_bounded_failure(monkeypatch):
    remote = FakeRemoteSync()
    monkeypatch.setattr('app.remote_stage.configured_task_store_sync', lambda: remote)
    request = httpx.Request('POST', 'https://fake.invalid')
    response = httpx.Response(429, request=request, headers={'Retry-After': '120'})
    error = openai.RateLimitError('rate limited', response=response, body=None)

    def fail(task, stage_input):
        raise error

    monkeypatch.setitem(STAGE_SERVICES, 'search', fail)
    with pytest.raises(StageExecutionError) as caught:
        run_stage('task-1', 'search', session_id='owner-1', job_id='job-test', input_hash='a' * 64)
    assert str(caught.value) == RATE_LIMIT_MESSAGE
    assert remote.failures[0]['event_type'] == 'rate_limited'
    assert remote.failures[0]['retry_after'] == 120


def test_remote_enqueue_failure_is_recorded_without_local_fallback(monkeypatch):
    remote = FakeRemoteSync()
    monkeypatch.setattr('app.remote_stage.configured_task_store_sync', lambda: remote)
    adapter = QueueAdapter(redis_url='')

    with pytest.raises(QueueEnqueueError):
        adapter.enqueue_stage('task-1', 'search', session_id='owner-1')
    assert remote.failures[0]['event_type'] == 'enqueue_failed'
    assert remote.failures[0]['expected_job_revision'] == 1
