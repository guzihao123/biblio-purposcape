import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from rq.job import Job
from rq.queue import Queue
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base, InviteSession, Task, TaskAnswer, TaskEvent, TaskJob
from app.queueing import QueueAdapter, STAGE_SERVICES, StageExecutionError
from app.schemas import CardId, TaskState


class DeterministicQueueAdapter(QueueAdapter):
    """Executes real enqueued callables only when the test asks for them."""

    def __init__(self):
        self.pending = []
        super().__init__(queue=self)

    def enqueue(self, function, *args, **kwargs):
        kwargs.pop('job_timeout', None)
        self.pending.append((function, args, kwargs))
        return SimpleNamespace(id=f'fake-job-{len(self.pending)}')

    def work_once(self):
        function, args, kwargs = self.pending.pop(0)
        return function(*args, **kwargs)


@pytest.fixture
def session_factory():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture(autouse=True)
def queue_database(monkeypatch, session_factory):
    monkeypatch.setattr('app.queueing.SessionLocal', session_factory)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def task(db):
    owner = InviteSession(id=str(uuid4()))
    task = Task(
        id=str(uuid4()),
        session_id=owner.id,
        state=TaskState.SEARCHING.value,
        next_card=None,
    )
    db.add(owner)
    db.add(task)
    db.flush()
    answer = TaskAnswer(
        task_id=task.id,
        card_id=CardId.YEARS.value,
        value={'years': [2020, 2026]},
        result_state=TaskState.SEARCHING.value,
        next_card=None,
    )
    db.add(answer)
    db.flush()
    db.add(
        TaskJob(
            id=str(uuid4()),
            task_id=task.id,
            answer_id=answer.id,
            kind='search',
        )
    )
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def fake_queue(monkeypatch):
    def search_stage(task, stage_input):
        return {
            'message': '检索与论文池整理完成',
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', search_stage)
    return DeterministicQueueAdapter()


def test_worker_saves_checkpoint_and_progress(db, task, fake_queue):
    fake_queue.enqueue_stage(task.id, 'search')
    fake_queue.work_once()

    db.expire_all()
    task = db.get(Task, task.id)
    events = [event.kind for event in task.events]
    assert events == ['queued', 'started', 'checkpoint', 'completed']
    assert task.progress.message == '检索与论文池整理完成'
    assert task.state == TaskState.DASHBOARD_READY.value
    assert task.next_card == CardId.ADJUSTMENT.value

    payloads = [event.payload for event in task.events]
    assert {payload['stage'] for payload in payloads} == {'search'}
    assert len({payload['input_hash'] for payload in payloads}) == 1
    assert len(payloads[0]['input_hash']) == 64
    for payload in payloads:
        assert datetime.fromisoformat(payload['timestamp']).utcoffset() is not None
    assert task.progress.checkpoint == payloads[2]
    assert task.progress.stage == 'search'
    assert task.progress.input_hash == payloads[0]['input_hash']
    assert task.progress.traceback is None
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'completed'


def test_local_stage_wraps_service_with_watchdog(db, task, fake_queue, monkeypatch):
    events = []

    class RecordingWatchdog:
        def __init__(self, stage, task_id, **kwargs):
            events.append(('init', stage, task_id, callable(kwargs.get('on_timeout'))))

        def __enter__(self):
            events.append(('enter',))

        def __exit__(self, exc_type, exc, traceback):
            events.append(('exit', exc_type.__name__ if exc_type else None))
            return False

    monkeypatch.setattr('app.queueing.StageWatchdog', RecordingWatchdog)

    def service(task, stage_input):
        events.append(('service',))
        return {
            'message': '检索与论文池整理完成',
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', service)
    fake_queue.enqueue_stage(task.id, 'search')
    fake_queue.work_once()

    assert events == [
        ('init', 'search', task.id, True),
        ('enter',),
        ('service',),
        ('exit', None),
    ]


def test_production_adapter_enqueues_rq_job_on_landscape(db, task, monkeypatch):
    monkeypatch.delenv('STAGE_JOB_TIMEOUT_SECONDS', raising=False)
    connection = fakeredis.FakeStrictRedis()
    adapter = QueueAdapter(connection=connection)

    enqueued = adapter.enqueue_stage(task.id, 'search')

    job = Job.fetch(enqueued.id, connection=connection)
    assert job.origin == 'landscape'
    assert job.func_name == 'app.queueing.run_stage'
    assert job.args == (task.id, 'search')
    assert job.timeout == 3600
    assert Queue('landscape', connection=connection).count == 1
    assert db.query(TaskEvent).filter_by(task_id=task.id, event_type='queued').count() == 1
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'queued'


def test_production_adapter_allows_a_longer_stage_job_timeout(db, task, monkeypatch):
    monkeypatch.setenv('STAGE_JOB_TIMEOUT_SECONDS', '7200')
    connection = fakeredis.FakeStrictRedis()
    adapter = QueueAdapter(connection=connection)

    enqueued = adapter.enqueue_stage(task.id, 'search')

    job = Job.fetch(enqueued.id, connection=connection)
    assert job.timeout == 7200


def test_worker_releases_session_before_long_service_and_finalizes_fresh(
    db, task, fake_queue, monkeypatch
):
    import app.queueing as queueing

    captured = {}
    original_finalize = queueing._finalize_success_with_retry

    def capture_finalize(task_id, stage, input_hash, result, session=None):
        captured['session'] = session
        return original_finalize(task_id, stage, input_hash, result, session=session)

    monkeypatch.setattr(queueing, '_finalize_success_with_retry', capture_finalize)

    def service(stage_task, stage_input):
        assert stage_task.id == task.id
        assert stage_task.session_id == task.session_id
        assert stage_task.skill_version_id == task.skill_version_id
        return {
            'message': '检索与论文池整理完成',
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', service)
    fake_queue.enqueue_stage(task.id, 'search')
    fake_queue.work_once()

    assert captured['session'] is None


def test_worker_failure_persists_safe_progress_and_redacted_traceback(
    db, task, fake_queue, monkeypatch, capsys
):
    secret = 'queue-test-secret-that-must-not-be-stored'
    monkeypatch.setenv('QUEUE_TEST_SECRET', secret)

    def fail_stage(task, stage_input):
        raise RuntimeError(f'provider failed with {secret}')

    monkeypatch.setitem(STAGE_SERVICES, 'broken', fail_stage)
    fake_queue.enqueue_stage(task.id, 'broken')
    with pytest.raises(StageExecutionError) as exc_info:
        fake_queue.work_once()

    assert str(exc_info.value) == '任务执行失败，请稍后重试。'
    db.expire_all()
    task = db.get(Task, task.id)
    events = list(task.events)
    assert [event.kind for event in events] == ['queued', 'started', 'failed']
    assert task.state == TaskState.ERROR.value
    assert task.progress.message == '任务执行失败，请稍后重试。'
    assert events[-1].payload['message'] == '任务执行失败，请稍后重试。'
    assert 'traceback' not in events[-1].payload
    assert secret not in json.dumps(events[-1].payload, ensure_ascii=False)
    assert 'Traceback' in task.progress.traceback
    assert 'RuntimeError' in task.progress.traceback
    assert secret not in task.progress.traceback
    failure_log = capsys.readouterr().err
    assert 'STAGE FAILURE' in failure_log
    assert task.id in failure_log
    assert 'RuntimeError' in failure_log
    assert secret not in failure_log
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'pending'


def test_health_reports_not_configured_without_pinging(monkeypatch):
    monkeypatch.setattr('app.queueing.get_settings', lambda: SimpleNamespace(redis_url=''))

    def unexpected_connection(*args, **kwargs):
        raise AssertionError('Redis must not be contacted without configuration')

    monkeypatch.setattr('app.queueing.redis.from_url', unexpected_connection)
    response = TestClient(app).get('/api/health')
    assert response.status_code == 200
    assert response.json()['worker'] == 'not_configured'


def test_health_reports_ready_only_after_redis_ping(monkeypatch):
    connection = fakeredis.FakeStrictRedis()
    requested = {}

    def connection_from_url(url, **kwargs):
        requested['url'] = url
        return connection

    monkeypatch.setattr(
        'app.queueing.get_settings',
        lambda: SimpleNamespace(redis_url='redis://fake.internal/4'),
    )
    monkeypatch.setattr('app.queueing.redis.from_url', connection_from_url)

    response = TestClient(app).get('/api/health')

    assert response.status_code == 200
    assert response.json()['worker'] == 'ready'
    assert requested == {'url': 'redis://fake.internal/4'}


def test_health_does_not_claim_ready_when_redis_ping_fails(monkeypatch):
    def failed_connection(*args, **kwargs):
        raise RedisError('connection unavailable')

    monkeypatch.setattr(
        'app.queueing.get_settings',
        lambda: SimpleNamespace(redis_url='redis://fake.internal/0'),
    )
    monkeypatch.setattr('app.queueing.redis.from_url', failed_connection)

    response = TestClient(app).get('/api/health')

    assert response.status_code == 200
    assert response.json()['worker'] == 'unavailable'


def test_worker_entry_uses_redis_url_and_landscape_queue(monkeypatch):
    import worker

    calls = {}
    connection = object()

    class FakeWorker:
        def __init__(self, queues, connection):
            calls['queues'] = queues
            calls['connection'] = connection

        def work(self):
            calls['worked'] = True

    def from_url(url):
        calls['url'] = url
        return connection

    monkeypatch.setenv('REDIS_URL', 'redis://worker.internal/2')
    monkeypatch.setattr(worker.Redis, 'from_url', staticmethod(from_url))
    monkeypatch.setattr(worker, 'ProtectedWorker', FakeWorker)

    worker.main()

    assert calls == {
        'url': 'redis://worker.internal/2',
        'queues': ['landscape'],
        'connection': connection,
        'worked': True,
    }


def test_finalize_success_retries_a_transient_db_error(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app import queueing

    calls = []

    def fake_finalize(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError('SELECT 1', {}, Exception('ssl eof'))
        return {'ok': True}

    monkeypatch.setattr(queueing, '_finalize_success', fake_finalize)
    monkeypatch.setattr(queueing, 'engine', type('E', (), {'dispose': staticmethod(lambda: None)})())

    assert queueing._finalize_success_with_retry('t', 'search', 'h', {}) == {'ok': True}
    assert len(calls) == 2
