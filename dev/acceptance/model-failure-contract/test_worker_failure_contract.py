"""Worker 层契约：模型异常经 run_stage 持久化后的安全不变量。

对每个异常场景断言：
- 任务进入 error、作业进入 failed，不产生 completed/checkpoint 成功事件；
- progress.checkpoint 为 None（不留下伪装成可恢复的成功检查点）；
- 对外只暴露安全文案，traceback/message/事件载荷全部无密钥、无
  Base URL 凭据、无请求头、无 Provider 私密正文。
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskAnswer, TaskEvent, TaskJob, TaskProgress
from app.queueing import SAFE_FAILURE_MESSAGE, STAGE_SERVICES, StageExecutionError, run_stage
from app.rate_limit import RATE_LIMIT_MESSAGE
from app.recovery import recover_interrupted_tasks, schedule_due_retries
from app.schemas import CardId, TaskState

from matrix_shared import (
    FAKE_API_KEY,
    FAKE_BASE_URL,
    assert_no_leaks,
    make_401_error,
    make_429_error,
    make_context_length_error,
    make_provider_body_echo_error,
    make_timeout_error,
)


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
    owner = InviteSession(id=str(uuid4()), client_ip='203.0.113.20')
    db.add(owner)
    task = Task(
        id=str(uuid4()),
        session_id=owner.id,
        state=TaskState.SEARCHING.value,
        next_card=None,
    )
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
    db.add(TaskJob(
        id=str(uuid4()),
        task_id=task.id,
        answer_id=answer.id,
        kind='generate',
    ))
    db.commit()
    db.refresh(task)
    return task


def register_failing_service(monkeypatch, error, calls):
    def service(task, stage_input):
        calls.append(stage_input)
        raise error

    monkeypatch.setitem(STAGE_SERVICES, 'generate', service)


def register_ok_service(monkeypatch):
    def service(task, stage_input):
        return {
            'message': '阶段完成：generate',
            'state': TaskState.DONE.value,
            'next_card': None,
            'checkpoint': {'stage': 'generate', 'clean': True},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'generate', service)


def run_generate(task):
    return run_stage(task.id, 'generate')


def failure_surfaces(db, task):
    """汇总所有对外/持久化表面：返回 (progress, events, surfaces)。"""
    db.expire_all()
    progress = db.get(TaskProgress, task.id)
    events = db.query(TaskEvent).filter_by(task_id=task.id).order_by(TaskEvent.id).all()
    surfaces = {
        'progress_message': progress.message,
        'progress_traceback': progress.traceback,
        'progress_checkpoint': progress.checkpoint,
        'event_payloads': json.dumps(
            [event.payload for event in events], ensure_ascii=False, sort_keys=True
        ),
        'event_types': [event.event_type for event in events],
    }
    return progress, events, surfaces


def assert_failure_contract(db, task, expected_event='failed'):
    progress, events, surfaces = failure_surfaces(db, task)
    for name in ('progress_message', 'progress_traceback', 'event_payloads'):
        assert_no_leaks(surfaces[name])
    # 无伪成功：不出现成功态事件，状态停在 error/failed。
    assert 'completed' not in surfaces['event_types']
    assert 'checkpoint' not in surfaces['event_types']
    assert expected_event in surfaces['event_types']
    assert progress.checkpoint is None
    row = db.get(Task, task.id)
    assert row.state == TaskState.ERROR.value
    assert row.next_card == task.next_card  # 失败记录不改变卡片导航
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.status == 'failed'
    return progress, events


def failed_events(events):
    return [event for event in events if event.event_type == 'failed']


def test_401_failure_is_safe_retryable_and_never_leaks_credentials(db, task, monkeypatch):
    monkeypatch.setenv('QWEN_API_KEY', FAKE_API_KEY)
    monkeypatch.setenv('QWEN_BASE_URL', FAKE_BASE_URL)
    calls = []
    register_failing_service(monkeypatch, make_401_error(), calls)

    with pytest.raises(StageExecutionError) as raised:
        run_generate(task)
    assert str(raised.value) == SAFE_FAILURE_MESSAGE
    assert_no_leaks(str(raised.value))
    assert len(calls) == 1

    progress, events = assert_failure_contract(db, task)
    failed = failed_events(events)
    assert len(failed) == 1
    payload = failed[0].payload
    assert payload['retryable'] is True
    assert payload['retry_action'] == {'action': 'retry_stage', 'stage': 'generate'}
    # 401 不是限流：不得携带 retry_after，避免恢复调度器按错误节奏重试。
    assert 'retry_after' not in payload
    # 诊断保留但已脱敏：固定文案 + 保留安全异常类型名，密钥不出现。
    assert 'AuthenticationError' in progress.traceback
    assert FAKE_API_KEY not in progress.traceback


def test_429_valid_retry_after_enters_bounded_retry_channel(db, task, session_factory, monkeypatch):
    calls = []
    register_failing_service(monkeypatch, make_429_error('120'), calls)

    with pytest.raises(StageExecutionError) as raised:
        run_generate(task)
    assert str(raised.value) == RATE_LIMIT_MESSAGE
    assert len(calls) == 1

    progress, events = assert_failure_contract(db, task, expected_event='rate_limited')
    limited = [event for event in events if event.event_type == 'rate_limited']
    assert len(limited) == 1
    assert limited[0].payload['retry_after'] == 120
    assert limited[0].payload['retryable'] is True
    assert 'Retry-After' not in (progress.message or '')
    assert 'Retry-After' not in (progress.traceback or '')

    enqueued = []
    due = datetime.now(timezone.utc) + timedelta(seconds=121)
    schedule_due_retries(
        session_factory=session_factory,
        now=lambda: due,
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
    )
    assert enqueued == [(task.id, 'generate', 0)]
    db.expire_all()
    event_types = [event.event_type for event in db.query(TaskEvent).filter_by(task_id=task.id).all()]
    assert 'retry_scheduled' in event_types
    assert db.query(TaskJob).filter_by(task_id=task.id).one().status == 'queued'


@pytest.mark.parametrize('bad_value', ['not-a-number', '-5', ''])
def test_429_invalid_retry_after_does_not_break_failure_recording(db, task, monkeypatch, bad_value):
    calls = []
    register_failing_service(monkeypatch, make_429_error(bad_value), calls)

    with pytest.raises(StageExecutionError):
        run_generate(task)
    assert len(calls) == 1
    assert_failure_contract(db, task)


def test_timeout_failure_is_safe_single_attempt(db, task, monkeypatch):
    calls = []
    register_failing_service(monkeypatch, make_timeout_error(), calls)

    with pytest.raises(StageExecutionError) as raised:
        run_generate(task)
    assert str(raised.value) == SAFE_FAILURE_MESSAGE
    # 缺口 D-02 演示：Worker 对超时不在本层做有界重试，单次失败后落库。
    assert len(calls) == 1
    assert_failure_contract(db, task)


def test_context_length_failure_is_safe(db, task, monkeypatch):
    calls = []
    register_failing_service(monkeypatch, make_context_length_error(), calls)

    with pytest.raises(StageExecutionError):
        run_generate(task)
    assert len(calls) == 1
    progress, _ = assert_failure_contract(db, task)
    assert 'BadRequestError' in progress.traceback


def test_provider_body_echo_is_redacted_from_every_surface(db, task, monkeypatch):
    """极端情况：异常消息夹带 Provider 私密正文 + 凭据，全部表面必须脱敏。"""
    monkeypatch.setenv('QWEN_API_KEY', FAKE_API_KEY)
    monkeypatch.setenv('QWEN_BASE_URL', FAKE_BASE_URL)
    calls = []
    register_failing_service(monkeypatch, make_provider_body_echo_error(), calls)

    with pytest.raises(StageExecutionError) as raised:
        run_generate(task)
    assert str(raised.value) == SAFE_FAILURE_MESSAGE
    assert_no_leaks(str(raised.value))

    progress, _ = assert_failure_contract(db, task)
    assert 'private_record' not in progress.traceback
    assert '[REDACTED_PROVIDER_BODY]' in progress.traceback
    assert '[REDACTED]' in progress.traceback


def test_failed_job_is_not_auto_settled_by_recovery(db, task, session_factory, monkeypatch):
    """不可恢复检查点检查：failed 作业不会被恢复流程误判为可结算。"""
    calls = []
    register_failing_service(monkeypatch, make_401_error(), calls)
    with pytest.raises(StageExecutionError):
        run_generate(task)

    results = recover_interrupted_tasks(
        session_factory=session_factory,
        stale_after=0,
        now=lambda: datetime.now(timezone.utc),
    )
    assert results == []
    _, _, surfaces = failure_surfaces(db, task)
    assert 'recovered' not in surfaces['event_types']


def test_success_path_still_records_checkpoint_for_control(db, task, monkeypatch):
    """对照组：成功路径落 checkpoint 且状态正确，证明失败路径的差异不是测试假象。"""
    register_ok_service(monkeypatch)
    checkpoint = run_generate(task)
    assert checkpoint['stage'] == 'generate'
    db.expire_all()
    assert db.get(Task, task.id).state == TaskState.DONE.value
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.status == 'completed'


def test_worker_quota_denial_records_rate_limited_with_retry_after(db, task, monkeypatch, isolated_limiter):
    """本地配额限流（唯一会带 retry_after 的通道）端到端进入有界重试调度。"""
    from app.rate_limit import RateLimitRule

    isolated_limiter.rules = {
        'retrieval': {'ip': RateLimitRule(1000, 3600)},
        'model': {'session': RateLimitRule(1, 3600)},
    }
    calls = []

    def counting_service(task, stage_input):
        calls.append(stage_input)
        return {
            'message': '阶段完成：generate',
            'state': TaskState.DONE.value,
            'next_card': None,
            'checkpoint': {'stage': 'generate', 'clean': True},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'generate', counting_service)
    assert run_generate(task)['stage'] == 'generate'
    assert len(calls) == 1

    # 换输入（追加一条答案）触发新的 model 配额消耗 → 超限拒绝。
    db.add(TaskAnswer(
        task_id=task.id,
        card_id=CardId.TERMS.value,
        value={'terms': ['fake topic']},
        result_state=TaskState.SEARCHING.value,
        next_card=None,
    ))
    db.commit()

    with pytest.raises(StageExecutionError):
        run_generate(task)
    assert len(calls) == 1  # 超限即拒，服务未被调用

    db.expire_all()
    progress = db.get(TaskProgress, task.id)
    assert_no_leaks(progress.message)
    assert_no_leaks(progress.traceback)
    assert progress.checkpoint is None
    assert db.get(Task, task.id).state == TaskState.ERROR.value
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.status == 'failed'

    events = db.query(TaskEvent).filter_by(task_id=task.id).order_by(TaskEvent.id).all()
    rate_limited_index = next(
        i for i, e in enumerate(events) if e.event_type == 'rate_limited'
    )
    after = events[rate_limited_index:]
    assert [e.event_type for e in after] == ['rate_limited']  # 拒绝后无伪成功事件
    assert_no_leaks(json.dumps([e.payload for e in after], ensure_ascii=False))
    assert after[0].payload['retry_after'] >= 1
    # 该事件正是恢复调度器有界重试的唯一入口。
    assert after[0].payload['retryable'] is True
