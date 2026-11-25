import threading
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.task_flow import CardId, TaskState, answer_card
from app.models import Base, InviteSession, Task, TaskAnswer, TaskEvent, TaskJob


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
def task_flow_database(monkeypatch, session_factory):
    monkeypatch.setattr('app.task_flow.SessionLocal', session_factory)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session(db):
    invite_session = InviteSession(id=str(uuid4()))
    db.add(invite_session)
    db.commit()
    return invite_session


@pytest.fixture
def task(db, session):
    task = Task(id=str(uuid4()), session_id=session.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def task_in_delivery(db, task):
    task.state = TaskState.ADJUSTING.value
    task.next_card = CardId.DELIVERY.value
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def set_state(db, task, state, next_card=None):
    task.state = state.value
    task.next_card = next_card.value if next_card is not None else None
    db.add(task)
    db.commit()
    db.refresh(task)


def test_card_and_state_wire_values_are_stable():
    assert {member.name: member.value for member in CardId} == {
        'DIRECTION': 'direction',
        'MODE': 'mode',
        'TERMS': 'terms',
        'YEARS': 'years',
        'ADJUSTMENT': 'adjustment',
        'DELIVERY': 'delivery',
    }
    assert {member.name: member.value for member in TaskState} == {
        'COLLECTING_MODE': 'collecting_mode',
        'COLLECTING_TERMS': 'collecting_terms',
        'COLLECTING_YEARS': 'collecting_years',
        'SEARCHING': 'searching',
        'DASHBOARD_READY': 'dashboard_ready',
        'ADJUSTING': 'adjusting',
        'DELIVERY_CONFIRMED': 'delivery_confirmed',
        'GENERATING': 'generating',
        'VERIFYING': 'verifying',
        'DONE': 'done',
        'ERROR': 'error',
    }


def test_opening_cards_follow_valid_transitions_and_start_one_search(db, task, session):
    direction = answer_card(task.id, CardId.DIRECTION, {'direction': 'urban resilience'}, session)
    assert direction.state == TaskState.COLLECTING_MODE
    assert direction.next_card == CardId.MODE
    assert direction.job_id is None

    mode = answer_card(task.id, CardId.MODE, {'mode': 'A'}, session)
    assert mode.state == TaskState.COLLECTING_TERMS
    assert mode.next_card == CardId.TERMS

    terms = answer_card(task.id, CardId.TERMS, {'terms': ['drainage', 'garage']}, session)
    assert terms.state == TaskState.COLLECTING_YEARS
    assert terms.next_card == CardId.YEARS

    years = answer_card(task.id, CardId.YEARS, {'years': [2020, 2026]}, session)
    assert years.state == TaskState.SEARCHING
    assert years.next_card is None
    assert years.job_id is not None

    db.refresh(task)
    assert task.state == TaskState.SEARCHING.value
    assert task.next_card is None
    assert db.query(TaskAnswer).filter_by(task_id=task.id).count() == 4
    job = db.query(TaskJob).filter_by(task_id=task.id).one()
    assert job.id == years.job_id
    assert job.kind == 'search'


def test_duplicate_answer_does_not_create_a_second_job(db, task, session):
    answer_card(task.id, CardId.DIRECTION, {'direction': 'urban resilience'}, session)
    first = answer_card(task.id, CardId.MODE, {'mode': 'A'}, session)
    second = answer_card(task.id, CardId.MODE, {'mode': 'A'}, session)
    assert first.job_id == second.job_id
    assert db.query(TaskAnswer).filter_by(task_id=task.id, card_id='mode').count() == 1


def test_duplicate_search_answer_returns_the_existing_job(db, task, session):
    set_state(db, task, TaskState.COLLECTING_YEARS, CardId.YEARS)

    first = answer_card(task.id, CardId.YEARS, {'years': [2020, 2026]}, session)
    second = answer_card(task.id, CardId.YEARS, {'years': [2020, 2026]}, session)

    assert first.job_id is not None
    assert first == second
    assert db.query(TaskAnswer).filter_by(task_id=task.id, card_id='years').count() == 1
    assert db.query(TaskJob).filter_by(task_id=task.id).count() == 1


def test_conflicting_late_answer_returns_409_with_zero_new_storage(db, task, session):
    answer_card(task.id, CardId.DIRECTION, {'direction': 'urban resilience'}, session)
    first = answer_card(task.id, CardId.MODE, {'mode': 'A'}, session)
    task_before_conflict = db.query(Task).filter_by(id=task.id).one().state

    with pytest.raises(HTTPException) as exc_info:
        answer_card(task.id, CardId.MODE, {'mode': 'B'}, session)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail['code'] == 'answer_conflict'
    answer = db.query(TaskAnswer).filter_by(task_id=task.id, card_id='mode').one()
    assert answer.value == {'mode': 'A'}
    assert db.query(Task).filter_by(id=task.id).one().state == task_before_conflict
    assert db.query(TaskEvent).filter_by(task_id=task.id, event_type='answer_conflict').count() == 0
    assert db.query(TaskAnswer).filter_by(task_id=task.id, card_id='mode').count() == 1


def test_adjustment_is_the_gateway_to_delivery(db, task, session):
    set_state(db, task, TaskState.DASHBOARD_READY, CardId.ADJUSTMENT)

    result = answer_card(task.id, CardId.ADJUSTMENT, {'adjustment': 'continue'}, session)

    assert result.state == TaskState.ADJUSTING
    assert result.next_card == CardId.DELIVERY
    assert result.job_id is None
    db.refresh(task)
    assert task.state == TaskState.ADJUSTING.value
    assert task.next_card == CardId.DELIVERY.value


def test_delivery_is_the_last_confirmation(db, task_in_delivery, session):
    result = answer_card(task_in_delivery.id, CardId.DELIVERY, {'form': 'B'}, session)
    assert result.state == TaskState.GENERATING
    assert result.next_card is None
    assert result.job_id is not None

    db.refresh(task_in_delivery)
    assert task_in_delivery.state == TaskState.GENERATING.value
    assert task_in_delivery.next_card is None
    job = db.query(TaskJob).filter_by(task_id=task_in_delivery.id).one()
    assert job.id == result.job_id
    assert job.kind == 'generate'

    repeated = answer_card(task_in_delivery.id, CardId.DELIVERY, {'form': 'B'}, session)
    assert repeated == result
    assert db.query(TaskJob).filter_by(task_id=task_in_delivery.id).count() == 1


def test_out_of_sequence_answer_is_rejected_without_side_effects(db, task, session):
    with pytest.raises(HTTPException) as exc_info:
        answer_card(task.id, CardId.DELIVERY, {'form': 'B'}, session)

    assert exc_info.value.status_code == 409
    assert db.query(TaskAnswer).filter_by(task_id=task.id).count() == 0
    assert db.query(TaskJob).filter_by(task_id=task.id).count() == 0
    assert db.query(TaskEvent).filter_by(task_id=task.id).count() == 0


def test_another_session_cannot_answer_a_task(db, task, session):
    other_session = InviteSession(id=str(uuid4()))
    db.add(other_session)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        answer_card(task.id, CardId.MODE, {'mode': 'A'}, other_session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == 'Task not found'
    assert db.query(TaskAnswer).filter_by(task_id=task.id).count() == 0


def test_startup_migrates_legacy_tasks_and_preserves_the_existing_row(tmp_path, monkeypatch):
    from app.db import initialize_database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
        connect_args={'check_same_thread': False},
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text('CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL)')
            )
            connection.execute(
                text("INSERT INTO tasks (id, session_id) VALUES ('legacy-task', 'legacy-session')")
            )

        initialize_database(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        monkeypatch.setattr('app.task_flow.SessionLocal', factory)

        with factory() as db:
            existing = db.get(Task, 'legacy-task')
            assert existing.id == 'legacy-task'
            assert existing.session_id == 'legacy-session'
            assert existing.state == TaskState.COLLECTING_MODE.value
            assert existing.next_card == CardId.DIRECTION.value
            owner = InviteSession(id='legacy-session')
            db.add(owner)
            db.commit()
            db.refresh(owner)

        answer_card('legacy-task', CardId.DIRECTION, {'direction': 'legacy direction'}, owner)
        result = answer_card('legacy-task', CardId.MODE, {'mode': 'A'}, owner)

        assert result.state == TaskState.COLLECTING_TERMS
        assert result.next_card == CardId.TERMS
        initialize_database(engine)
        with factory() as db:
            migrated = db.get(Task, 'legacy-task')
            assert migrated.session_id == 'legacy-session'
            assert migrated.state == TaskState.COLLECTING_TERMS.value
            assert migrated.next_card == CardId.TERMS.value
            answer = db.query(TaskAnswer).filter_by(task_id='legacy-task', card_id='mode').one()
            assert answer.value == {'mode': 'A'}
    finally:
        engine.dispose()


def test_concurrent_identical_answers_resolve_the_unique_race_to_one_answer_and_job(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={'check_same_thread': False, 'timeout': 10},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr('app.task_flow.SessionLocal', factory)

    with factory() as db:
        db.add(InviteSession(id='shared-session'))
        db.add(
            Task(
                id='shared-task',
                session_id='shared-session',
                state=TaskState.COLLECTING_YEARS.value,
                next_card=CardId.YEARS.value,
            )
        )
        db.commit()

    barrier = threading.Barrier(2)
    results = {}
    failures = {}

    def run_answer(role):
        try:
            barrier.wait(timeout=10)
            results[role] = answer_card(
                'shared-task',
                CardId.YEARS,
                {'years': [2020, 2026]},
                InviteSession(id='shared-session'),
            )
        except BaseException as error:
            failures[role] = error

    threads = [
        threading.Thread(target=run_answer, args=('winner',), name='winner'),
        threading.Thread(target=run_answer, args=('loser',), name='loser'),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == {}
    assert len(results) == 2
    assert results['winner'] == results['loser']
    assert results['winner'].job_id is not None

    with factory() as db:
        answers = db.query(TaskAnswer).filter_by(task_id='shared-task', card_id='years').all()
        jobs = db.query(TaskJob).filter_by(task_id='shared-task').all()
        assert len(answers) == 1
        assert len(jobs) == 1
        assert answers[0].value == {'years': [2020, 2026]}
        assert jobs[0].answer_id == answers[0].id
        assert jobs[0].id == results['winner'].job_id
    engine.dispose()
