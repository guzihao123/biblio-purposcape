import json
from types import SimpleNamespace
from uuid import uuid4

import fakeredis
import pytest
from redis.exceptions import RedisError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskAnswer, TaskJob, TaskProgress
from app.queueing import (
    QueueAdapter,
    QueueEnqueueError,
    SAFE_ENQUEUE_MESSAGE,
    SAFE_FAILURE_MESSAGE,
    STAGE_SERVICES,
    StageExecutionError,
    run_stage,
)
from app.schemas import CardId, TaskState


class DeterministicQueueAdapter(QueueAdapter):
    def __init__(self):
        self.pending = []
        super().__init__(queue=self)

    def enqueue(self, function, *args, **kwargs):
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
    db.add_all([owner, task])
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
    calls = []

    def search_stage(task, stage_input):
        calls.append(stage_input)
        return {
            'message': '检索与论文池整理完成',
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
            'checkpoint': {'papers_count': 5},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', search_stage)
    queue = DeterministicQueueAdapter()
    queue.calls = calls
    return queue


def test_redis_unavailable_during_enqueue_never_leaves_false_queued_state(
    db, task, monkeypatch, session_factory
):
    secret = 'redis-enqueue-secret'
    monkeypatch.setenv('QUEUE_FAILURE_TEST_SECRET', secret)

    class UnavailableRedis(fakeredis.FakeStrictRedis):
        def pipeline(self, *args, **kwargs):
            raise RedisError(
                f'redis://:{secret}@private.internal/0 at /Users/private/server.py'
            )

    adapter = QueueAdapter(
        connection=UnavailableRedis(),
        session_factory=session_factory,
    )

    def unexpected_global_session():
        raise AssertionError('The adapter must use its injected session factory')

    monkeypatch.setattr('app.queueing.SessionLocal', unexpected_global_session)
    with pytest.raises(QueueEnqueueError) as exc_info:
        adapter.enqueue_stage(task.id, 'search')

    assert str(exc_info.value) == SAFE_ENQUEUE_MESSAGE
    public_exception = str(exc_info.value)
    assert secret not in public_exception
    assert 'private.internal' not in public_exception
    assert '/Users/' not in public_exception

    db.expire_all()
    failed_task = db.get(Task, task.id)
    events = list(failed_task.events)
    assert [event.kind for event in events] == ['queued', 'enqueue_failed']
    assert failed_task.state == TaskState.ERROR.value
    assert failed_task.progress.message == SAFE_ENQUEUE_MESSAGE
    assert failed_task.progress.checkpoint is None
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'failed'
    failure = events[-1].payload
    assert failure['message'] == SAFE_ENQUEUE_MESSAGE
    assert failure['retryable'] is True
    assert failure['retry_action'] == {'action': 'retry_stage', 'stage': 'search'}
    assert 'traceback' not in failure
    assert secret not in json.dumps(failure, ensure_ascii=False)
    assert '/Users/' not in json.dumps(failure, ensure_ascii=False)
    assert secret not in failed_task.progress.traceback


def test_unknown_stage_is_a_safe_real_failure(db, task):
    queue = DeterministicQueueAdapter()
    queue.enqueue_stage(task.id, 'not-implemented')

    with pytest.raises(StageExecutionError) as exc_info:
        queue.work_once()

    assert str(exc_info.value) == SAFE_FAILURE_MESSAGE
    db.expire_all()
    failed_task = db.get(Task, task.id)
    assert failed_task.state == TaskState.ERROR.value
    assert failed_task.progress.message == SAFE_FAILURE_MESSAGE
    assert [event.kind for event in failed_task.events] == ['queued', 'started', 'failed']
    failure = failed_task.events[-1].payload
    assert failure['stage'] == 'not-implemented'
    assert failure['message'] == SAFE_FAILURE_MESSAGE
    assert 'traceback' not in failure
    assert 'No execution service' not in json.dumps(failure)


def test_rq_execution_failure_marks_matching_job_failed_without_public_details(
    db, task, monkeypatch
):
    secret = 'provider-secret'
    monkeypatch.setenv('PROVIDER_TEST_SECRET', secret)

    def broken_service(task, stage_input):
        raise RuntimeError(f'{secret} in /Users/private/provider.py')

    monkeypatch.setitem(STAGE_SERVICES, 'search', broken_service)
    queue = DeterministicQueueAdapter()
    queue.enqueue_stage(task.id, 'search')
    with pytest.raises(StageExecutionError) as exc_info:
        queue.work_once()

    assert str(exc_info.value) == SAFE_FAILURE_MESSAGE
    db.expire_all()
    failed_task = db.get(Task, task.id)
    failure = failed_task.events[-1].payload
    assert failed_task.state == TaskState.ERROR.value
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'failed'
    assert failure['message'] == SAFE_FAILURE_MESSAGE
    assert secret not in json.dumps(failure)
    assert '/Users/' not in json.dumps(failure)
    assert secret not in failed_task.progress.traceback


def test_sensitive_failure_is_fully_redacted_detached_and_retryable(
    db, task, monkeypatch
):
    environment_value = 'fake-environment-value-a90e'
    monkeypatch.setenv('WORKER_REDACTION_TEST_SECRET', environment_value)
    private_values = [
        'fake-token-redaction-7f3a',
        'fake-password-redaction-91b2',
        'fake-secret-redaction-c814',
        'fake-provider-body-private-record-52de',
        'fake_private_customers',
        'fake-url-password-63ad',
        '/Users/fake-worker/private/fake-task.db',
        r'C:\fake-server\private\fake-task.db',
        environment_value,
    ]
    marker = 'OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE'
    message = (
        f'{marker}; token=fake-token-redaction-7f3a; '
        'password="fake-password-redaction-91b2"; '
        'secret: fake-secret-redaction-c814; '
        'SQL: SELECT * FROM fake_private_customers; '
        'Provider response body={"private_record":'
        '"fake-provider-body-private-record-52de"}; '
        'redis://fake-user:fake-url-password-63ad@private.internal:6379/0; '
        '/Users/fake-worker/private/fake-task.db; '
        r'C:\fake-server\private\fake-task.db' + f'; env={environment_value}'
    )

    def broken_service(task, stage_input):
        raise RuntimeError(message)

    monkeypatch.setitem(STAGE_SERVICES, 'search', broken_service)
    queue = DeterministicQueueAdapter()
    queue.enqueue_stage(task.id, 'search')
    with pytest.raises(StageExecutionError) as exc_info:
        queue.work_once()

    public_error = exc_info.value
    assert str(public_error) == SAFE_FAILURE_MESSAGE
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    db.expire_all()
    failed_task = db.get(Task, task.id)
    failure = failed_task.events[-1].payload
    protected = failed_task.progress.traceback
    event_text = json.dumps(failure, ensure_ascii=False)
    for private_value in private_values:
        assert private_value not in protected
        assert private_value not in event_text
        assert private_value not in str(public_error)
    assert 'SELECT' not in protected
    assert 'private_record' not in protected
    assert '/Users/fake-worker' not in protected
    assert r'C:\fake-server' not in protected
    assert 'Traceback (most recent call last)' in protected
    assert 'RuntimeError' in protected
    assert marker in protected
    assert failure['stage'] == 'search'
    assert failure['retryable'] is True
    assert failure['retry_action'] == {'action': 'retry_stage', 'stage': 'search'}
    assert 'traceback' not in failure

    def recovered_service(task, stage_input):
        return {
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
            'checkpoint': {'papers_count': 5},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', recovered_service)
    checkpoint = run_stage(task.id, 'search')

    assert checkpoint['papers_count'] == 5
    db.expire_all()
    recovered = db.get(Task, task.id)
    assert recovered.state == TaskState.DASHBOARD_READY.value
    assert recovered.progress.traceback is None
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'completed'


def test_checkpoint_commit_failure_is_retryable_and_later_completes(
    db, task, fake_queue, monkeypatch
):
    secret = 'checkpoint-write-secret'
    monkeypatch.setenv('CHECKPOINT_TEST_SECRET', secret)
    original_commit = Session.commit

    with monkeypatch.context() as patch:
        def fail_only_checkpoint_commit(session):
            progress = session.get(TaskProgress, task.id)
            if progress is not None and progress.checkpoint is not None:
                raise RuntimeError(f'{secret} at /Users/private/database.py')
            return original_commit(session)

        patch.setattr(Session, 'commit', fail_only_checkpoint_commit)
        fake_queue.enqueue_stage(task.id, 'search')
        with pytest.raises(StageExecutionError) as exc_info:
            fake_queue.work_once()

    assert str(exc_info.value) == SAFE_FAILURE_MESSAGE
    db.expire_all()
    failed_task = db.get(Task, task.id)
    assert failed_task.state == TaskState.ERROR.value
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'failed'
    assert [event.kind for event in failed_task.events] == ['queued', 'started', 'failed']
    assert failed_task.progress.checkpoint is None
    assert secret not in failed_task.events[-1].payload['message']
    assert '/Users/' not in failed_task.events[-1].payload['message']

    # A retry is permitted from the explicit failed state and the stable input hash.
    checkpoint = run_stage(task.id, 'search')

    assert checkpoint['papers_count'] == 5
    db.expire_all()
    recovered = db.get(Task, task.id)
    assert recovered.state == TaskState.DASHBOARD_READY.value
    assert recovered.progress.checkpoint == checkpoint
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'completed'
    assert [event.kind for event in recovered.events] == [
        'queued',
        'started',
        'failed',
        'started',
        'checkpoint',
        'completed',
    ]


def test_duplicate_completed_execution_returns_checkpoint_without_rerunning_service(
    db, task, fake_queue
):
    fake_queue.enqueue_stage(task.id, 'search')
    first_checkpoint = fake_queue.work_once()
    events_after_success = [event.kind for event in db.get(Task, task.id).events]

    duplicate_checkpoint = run_stage(task.id, 'search')

    assert duplicate_checkpoint == first_checkpoint
    assert len(fake_queue.calls) == 1
    db.expire_all()
    assert [event.kind for event in db.get(Task, task.id).events] == events_after_success


def test_duplicate_started_execution_does_not_call_service_twice(db, task, fake_queue):
    fake_queue.enqueue_stage(task.id, 'search')
    function, args, kwargs = fake_queue.pending.pop(0)

    # Simulate a second RQ delivery observing the first delivery's started commit.
    job = db.query(TaskJob).filter_by(task_id=task.id, kind='search').one()
    job.status = 'started'
    progress = db.get(TaskProgress, task.id)
    progress.stage = 'search'
    progress.message = '正在检索与整理论文池'
    db.commit()

    result = function(*args, **kwargs)

    assert result == {}
    assert fake_queue.calls == []
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'started'



def _stage_counter_values(limiter, operation):
    return sorted(
        int(limiter.connection.get(key))
        for key in limiter.connection.keys(f'*{operation}*')
    )


def test_worker_search_consumes_retrieval_and_model_quotas_once(
    db, task, fake_queue, isolated_rate_limiter
):
    fake_queue.enqueue_stage(task.id, 'search')
    fake_queue.work_once()
    run_stage(task.id, 'search')

    assert _stage_counter_values(isolated_rate_limiter, 'retrieval') == [1, 1]
    assert _stage_counter_values(isolated_rate_limiter, 'model') == [1, 1]
    assert len(fake_queue.calls) == 1


def test_worker_rate_limit_is_a_safe_retryable_failure_without_service_call(
    db, task, fake_queue, isolated_rate_limiter
):
    from app.rate_limit import RateLimitRule

    isolated_rate_limiter.clock = lambda: 0
    isolated_rate_limiter.rules = {
        'retrieval': {
            'session': RateLimitRule(1, 3600),
            'ip': RateLimitRule(10, 3600),
        },
        'model': {
            'session': RateLimitRule(10, 3600),
            'ip': RateLimitRule(10, 3600),
        },
    }
    exhausted = isolated_rate_limiter.consume(
        'retrieval',
        session_id=task.session_id,
        source_ip='unknown',
        idempotency_key='exhaust-retrieval',
    )
    assert exhausted.allowed

    fake_queue.enqueue_stage(task.id, 'search')
    with pytest.raises(StageExecutionError) as exc_info:
        fake_queue.work_once()

    assert str(exc_info.value) == '请求过于频繁，请稍后重试。'
    assert fake_queue.calls == []
    db.expire_all()
    failed_task = db.get(Task, task.id)
    assert failed_task.state == TaskState.ERROR.value
    assert [event.kind for event in failed_task.events] == [
        'queued', 'started', 'rate_limited'
    ]
    event = failed_task.events[-1].payload
    assert event['retry_after'] == 3600
    assert event['retryable'] is True
    assert 'traceback' not in event
    assert db.query(TaskJob).filter_by(task_id=task.id, kind='search').one().status == 'failed'
    assert _stage_counter_values(isolated_rate_limiter, 'model') == []
