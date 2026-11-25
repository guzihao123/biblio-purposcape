"""Stage progress is advisory: it must be visible, safe, and never fail a stage."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskAnswer, TaskJob, TaskProgress
from app.progress_reporter import (
    PHASES,
    NullReporter,
    TaskProgressReporter,
    current_reporter,
    report_phase,
    report_stage_phase,
    stage_reporting,
)
from app.queueing import (
    SAFE_FAILURE_MESSAGE,
    STAGE_SERVICES,
    StageExecutionError,
    run_stage,
)
from app.schemas import CardId, TaskState


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
    record = Task(
        id=str(uuid4()),
        session_id=owner.id,
        state=TaskState.SEARCHING.value,
        next_card=None,
    )
    db.add_all([owner, record])
    db.flush()
    answer = TaskAnswer(
        task_id=record.id,
        card_id=CardId.YEARS.value,
        value={'choice': 'D'},
        result_state=TaskState.SEARCHING.value,
        next_card=None,
    )
    db.add(answer)
    db.flush()
    db.add(TaskJob(
        id=str(uuid4()),
        task_id=record.id,
        answer_id=answer.id,
        kind='search',
    ))
    db.add(TaskProgress(task_id=record.id, stage='search', message='', percent=0))
    db.commit()
    return record


def test_phase_table_covers_declared_search_and_generate_stages():
    assert {name for stage, name in PHASES if stage == 'search'} == {
        'retrieve', 'classify', 'factors', 'relations', 'stats', 'graph', 'upload',
    }
    assert {name for stage, name in PHASES if stage == 'generate'} == {
        'components', 'outline_sample', 'body', 'review', 'office', 'upload',
    }
    for stage in ('search', 'generate'):
        entries = [entry for key, entry in PHASES.items() if key[0] == stage]
        percents = [entry[2] for entry in entries]
        assert percents == sorted(percents)
        assert all(0 < value < 100 for value in percents)
        assert all(len(entry[1]) <= 500 for entry in entries)


def test_reporter_writes_committed_message_and_percent_without_touching_lifecycle(db, task, session_factory):
    progress = db.get(TaskProgress, task.id)
    progress.input_hash = 'original-hash'
    progress.checkpoint = {'stage': 'search', 'kept': True}
    stage = progress.stage
    db.commit()

    reporter = TaskProgressReporter(task.id, 'search', session_factory=session_factory)
    with stage_reporting(reporter) as injected:
        assert isinstance(current_reporter(), TaskProgressReporter)
        assert injected is reporter
        report_stage_phase('search', 'factors')

    db.refresh(progress)
    assert progress.message == '正在分析论文：因素抽取'
    assert progress.percent == 35
    assert progress.stage == stage
    assert progress.input_hash == 'original-hash'
    assert progress.checkpoint == {'stage': 'search', 'kept': True}
    assert progress.traceback is None
    assert isinstance(current_reporter(), NullReporter)


def test_reporter_never_creates_missing_progress_row(db, task, session_factory):
    db.delete(db.get(TaskProgress, task.id))
    db.commit()
    reporter = TaskProgressReporter(task.id, 'search', session_factory=session_factory)
    report_phase('search.retrieve', '正在检索与整理论文池', 10, reporter=reporter)
    assert db.get(TaskProgress, task.id) is None


def test_reporter_clamps_percent_and_redacts_free_form_message(db, task, session_factory):
    reporter = TaskProgressReporter(task.id, 'search', session_factory=session_factory)
    report_phase(
        'search.retrieve',
        'api_key=TOPSECRET_PROGRESS_VALUE at /Users/private/worker.py',
        999,
        reporter=reporter,
    )
    progress = db.get(TaskProgress, task.id)
    db.refresh(progress)
    assert progress.percent == 100
    assert 'TOPSECRET_PROGRESS_VALUE' not in progress.message
    assert '/Users/private/worker.py' not in progress.message
    assert '[REDACTED]' in progress.message or '[REDACTED_PATH]' in progress.message
    report_phase('search.retrieve', '正在检索与整理论文池', -5, reporter=reporter)
    db.refresh(progress)
    assert progress.percent == 0


def test_reporting_failures_are_swallowed(monkeypatch, db, task):
    class BrokenSession:
        def __call__(self):
            raise RuntimeError('database password=TOPSECRET_PROGRESS_VALUE')

    broken = TaskProgressReporter(task.id, 'search', session_factory=BrokenSession())
    report_phase('search.retrieve', '正在检索与整理论文池', 10, reporter=broken)
    assert 'TOPSECRET_PROGRESS_VALUE' not in (db.get(TaskProgress, task.id).message or '')

    class BrokenReporter:
        def update(self, *args):
            raise RuntimeError('reporter exploded')

    report_phase('search.retrieve', '正在检索与整理论文池', 10, reporter=BrokenReporter())
    report_stage_phase('search', 'not-a-phase', reporter=BrokenReporter())


def test_run_stage_injects_reporter_and_finalizes_at_100(db, task, monkeypatch):
    observed = {}

    def search_stage(stage_task, stage_input):
        observed['reporter'] = current_reporter()
        observed['stage_input'] = stage_input
        report_stage_phase('search', 'graph')
        return {
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
            'message': '检索与论文池整理完成',
            'checkpoint': {'stage': 'search'},
        }

    monkeypatch.setitem(STAGE_SERVICES, 'search', search_stage)
    run_stage(task.id, 'search')

    assert isinstance(observed['reporter'], TaskProgressReporter)
    assert 'reporter' not in observed['stage_input']
    progress = db.get(TaskProgress, task.id)
    db.refresh(progress)
    assert progress.message == '检索与论文池整理完成'
    assert progress.percent == 100
    assert progress.checkpoint['stage'] == 'search'


def test_run_stage_failure_keeps_public_safe_message(db, task, monkeypatch):
    secret = 'TOPSECRET_STAGE_FAILURE'

    def failing_stage(stage_task, stage_input):
        report_stage_phase('search', 'stats')
        raise RuntimeError(f'api_key={secret} at /Users/private/failure.py')

    monkeypatch.setitem(STAGE_SERVICES, 'search', failing_stage)
    with pytest.raises(StageExecutionError) as raised:
        run_stage(task.id, 'search')

    assert str(raised.value) == SAFE_FAILURE_MESSAGE
    assert raised.value.__cause__ is None
    progress = db.get(TaskProgress, task.id)
    db.refresh(progress)
    assert progress.message == SAFE_FAILURE_MESSAGE
    assert progress.percent != 100
    assert secret not in (progress.traceback or '')
    assert '/Users/private/failure.py' not in (progress.traceback or '')
    db.refresh(task)
    assert task.state == TaskState.ERROR.value
