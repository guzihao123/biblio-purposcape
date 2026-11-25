"""有界重试与最终失败契约。

本地配额限流（rate_limited 事件）驱动恢复调度器的有界重试：
- 未达上限 → 重新排队一次并记录 retry_scheduled；
- 达到 max_attempts → 记录 retry_exhausted，不再重试，任务保持 error。

同时用现状演示测试记录两个缺口：
- D-01 Provider 429 不进 rate_limited 通道，永远不会被自动重试；
- D-02 openai 超时/连接错误不在 TRANSIENT_ERRORS 内，retry_call 也不会
  把它们当作瞬时错误（且模型调用点目前没有接 retry_call）。
"""

import openai
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskEvent, TaskJob, TaskProgress
from app.recovery import retry_call, schedule_due_retries
from app.schemas import TaskState


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


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def utcnow():
    return datetime.now(timezone.utc)


def make_failed_job(db, rate_limited_events):
    owner = InviteSession(id=str(uuid4()), client_ip='203.0.113.30')
    db.add(owner)
    task = Task(id=str(uuid4()), session_id=owner.id, state=TaskState.ERROR.value)
    db.add(task)
    db.flush()
    answer_id = 1
    db.add(TaskJob(id=str(uuid4()), task_id=task.id, answer_id=answer_id, kind='generate', status='failed'))
    db.add(TaskProgress(task_id=task.id, stage='generate', message='失败', input_hash='hash'))
    for retry_after in rate_limited_events:
        db.add(TaskEvent(
            task_id=task.id,
            event_type='rate_limited',
            payload={'retry_after': retry_after, 'message': '请求过于频繁'},
        ))
    db.commit()
    return task


def age_progress(db, task, seconds):
    old = utcnow() - timedelta(seconds=seconds)
    db.execute(text('UPDATE task_progress SET updated_at = :old'), {'old': old.isoformat()})
    db.commit()


def test_bounded_retry_requeues_until_attempt_cap_then_marks_exhausted(db, session_factory):
    task = make_failed_job(db, rate_limited_events=[60, 60])  # 已有 2 次限流
    age_progress(db, task, seconds=90)
    enqueued = []

    schedule_due_retries(
        session_factory=session_factory,
        now=utcnow,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
        max_attempts=3,
    )
    # 第 3 次（上限内）→ 重新排队。
    assert len(enqueued) == 1
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.status == 'queued'

    # 第 4 次运行：作业已重新 queued（不在 failed 集合），且事件数仍 >= max_attempts。
    db.expire_all()
    db.add(TaskEvent(task_id=task.id, event_type='rate_limited', payload={'retry_after': 60}))
    db.query(TaskJob).filter_by(task_id=task.id).one().status = 'failed'
    db.commit()
    age_progress(db, task, seconds=90)
    enqueued.clear()

    schedule_due_retries(
        session_factory=session_factory,
        now=utcnow,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
        max_attempts=3,
    )
    assert enqueued == []
    exhausted = [
        event for event in db.query(TaskEvent).filter_by(task_id=task.id).all()
        if event.event_type == 'retry_exhausted'
    ]
    assert len(exhausted) == 1
    # 最终失败：重试耗尽后不再进入完成态（重排期曾回到 generating）。
    assert db.get(Task, task.id).state != TaskState.DONE.value


def test_exhausted_retry_emits_single_terminal_event_and_stays_failed(db, session_factory):
    task = make_failed_job(db, rate_limited_events=[60, 60, 60])  # 已达 max_attempts
    age_progress(db, task, seconds=90)
    enqueued = []

    schedule_due_retries(
        session_factory=session_factory,
        now=utcnow,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
        max_attempts=3,
    )
    assert enqueued == []
    events = db.query(TaskEvent).filter_by(task_id=task.id).all()
    assert sum(1 for e in events if e.event_type == 'retry_exhausted') == 1
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.status == 'failed'
    assert db.get(Task, task.id).state == TaskState.ERROR.value


def test_retry_not_due_yet_waits_for_retry_after(db, session_factory):
    task = make_failed_job(db, rate_limited_events=[300])
    age_progress(db, task, seconds=10)  # 远未到 300s
    enqueued = []

    schedule_due_retries(
        session_factory=session_factory,
        now=utcnow,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
    )
    assert enqueued == []
    assert db.query(TaskJob).filter_by(task_id=task.id).one().status == 'failed'


def test_generic_model_failure_never_enters_bounded_retry_channel(db, session_factory):
    """缺口 D-01：Provider 401/429/超时只产生 failed 事件（无 retry_after），
    恢复调度器不会自动重试它们——有界重试目前只认本地配额的 rate_limited。"""
    task = make_failed_job(db, rate_limited_events=[])
    db.add(TaskEvent(task_id=task.id, event_type='failed', payload={'retryable': True}))
    db.commit()
    age_progress(db, task, seconds=10_000)
    enqueued = []

    schedule_due_retries(
        session_factory=session_factory,
        now=utcnow,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
    )
    assert enqueued == []
    events = [e.event_type for e in db.query(TaskEvent).filter_by(task_id=task.id).all()]
    assert 'retry_exhausted' not in events
    assert 'retry_scheduled' not in events


def test_retry_call_treats_builtin_and_openai_transient_errors_as_retryable():
    """内置及 OpenAI 超时/连接错误都按相同上限进行有界重试。"""
    attempts = []

    def builtin_timeout():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError('temporary')
        return 'ok'

    assert retry_call(builtin_timeout, attempts=3, base_delay=0, jitter=0, sleep=lambda s: None) == 'ok'
    assert len(attempts) == 3

    openai_attempts = []

    def openai_timeout():
        openai_attempts.append(1)
        raise openai.APITimeoutError(request=None)

    with pytest.raises(openai.APITimeoutError):
        retry_call(openai_timeout, attempts=3, base_delay=0, jitter=0, sleep=lambda s: None)
    assert len(openai_attempts) == 3

    connection_attempts = []

    def openai_connection_error():
        connection_attempts.append(1)
        raise openai.APIConnectionError(request=None)

    with pytest.raises(openai.APIConnectionError):
        retry_call(openai_connection_error, attempts=3, base_delay=0, jitter=0, sleep=lambda s: None)
    assert len(connection_attempts) == 3
