from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adjustments import AdjustmentError, apply_adjustment
from app.models import Base, InviteSession, Task, TaskAnswer, TaskEvent, TaskJob
from app.schemas import CardId, TaskState
from app.task_flow import answer_card


def dashboard_task(**overrides):
    values = {
        'state': TaskState.DASHBOARD_READY,
        'mode': 'A',
        'terms': ['urban flooding'],
        'from_year': 2022,
        'user_results': '',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_year_change_only_rebuilds_limited_scope():
    result = apply_adjustment(
        dashboard_task(),
        {'years': {'choice': 'B', 'from_year': 2021}},
    )

    assert result.rebuild == {'limited_search', 'limited_topics', 'limited_pool_charts'}
    assert result.reuse == {
        'unlimited_search',
        'trend',
        'compare',
        'unlimited_pool_charts',
    }


def test_term_change_rebuilds_both_scopes_and_derived_analysis():
    result = apply_adjustment(
        dashboard_task(),
        {'terms': ['drainage resilience']},
    )

    assert {
        'unlimited_search',
        'limited_search',
        'trend',
        'compare',
        'unlimited_pool_charts',
        'limited_pool_charts',
        'writing_pool',
        'reading_pool',
    } <= result.rebuild
    assert result.reuse == set()


def test_mode_change_reloads_mode_and_reselects_pools_without_retrieving_again():
    result = apply_adjustment(dashboard_task(), {'mode': 'D'})

    assert result.rebuild == {'writing_pool', 'reading_pool', 'outline', 'body'}
    assert {
        'unlimited_search',
        'limited_search',
        'trend',
        'compare',
        'unlimited_pool_charts',
        'limited_pool_charts',
    } <= result.reuse
    assert result.mode_template == 'D'


def test_original_plan_has_veto_power_and_requests_delivery():
    result = apply_adjustment(
        dashboard_task(),
        {'continue': True, 'terms': ['ignored'], 'years': {'from_year': 2020}},
    )

    assert result.next_card == CardId.DELIVERY
    assert result.state == TaskState.ADJUSTING
    assert result.rebuild == set()


def test_mode_c_requests_user_results_once_before_delivery():
    result = apply_adjustment(dashboard_task(), {'mode': 'C'})

    assert result.follow_up == 'user_results'
    assert result.next_card != CardId.DELIVERY


def test_mode_c_with_results_does_not_request_them_again():
    result = apply_adjustment(
        dashboard_task(user_results='The intervention reduced readmissions.'),
        {'mode': 'C'},
    )

    assert result.follow_up is None


def test_no_adjustment_after_delivery_is_rejected():
    with pytest.raises(AdjustmentError, match='delivery has already been confirmed'):
        apply_adjustment(
            dashboard_task(state=TaskState.GENERATING),
            {'continue': True},
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


@pytest.fixture
def db(session_factory, monkeypatch):
    monkeypatch.setattr('app.task_flow.SessionLocal', session_factory)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def owner(db):
    owner = InviteSession(id=str(uuid4()))
    db.add(owner)
    db.commit()
    return owner


@pytest.fixture
def searchable_task(db, owner):
    task = Task(id=str(uuid4()), session_id=owner.id)
    db.add(task)
    db.commit()
    answer_card(task.id, CardId.DIRECTION, {'direction': 'urban resilience'}, owner)
    answer_card(task.id, CardId.MODE, {'mode': 'A'}, owner)
    answer_card(task.id, CardId.TERMS, {'terms': ['urban flooding']}, owner)
    answer_card(task.id, CardId.YEARS, {'choice': 'B', 'from_year': 2021}, owner)
    task.state = TaskState.DASHBOARD_READY.value
    task.next_card = CardId.ADJUSTMENT.value
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_revision_after_adjustment_is_not_treated_as_a_late_duplicate(db, searchable_task, owner):
    selected = answer_card(
        searchable_task.id,
        CardId.ADJUSTMENT,
        {'adjustment': ['terms']},
        owner,
    )
    assert selected.next_card == CardId.TERMS

    revised = answer_card(
        searchable_task.id,
        CardId.TERMS,
        {'terms': ['drainage resilience']},
        owner,
    )

    assert revised.state == TaskState.SEARCHING
    assert revised.job_id is not None
    assert db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='terms').one().value == {
        'terms': ['drainage resilience']
    }
    assert db.query(TaskJob).filter_by(task_id=searchable_task.id, kind='search').count() == 1
    assert db.query(TaskEvent).filter_by(task_id=searchable_task.id, event_type='answer_revised').count() == 1


def test_repeated_adjustment_loops_reuse_the_search_job_without_duplicate_answers(db, searchable_task, owner):
    for new_year in (2020, 2019):
        answer_card(
            searchable_task.id,
            CardId.ADJUSTMENT,
            {'adjustment': ['years']},
            owner,
        )
        result = answer_card(
            searchable_task.id,
            CardId.YEARS,
            {'choice': 'C', 'from_year': new_year},
            owner,
        )
        assert result.state == TaskState.SEARCHING
        db.refresh(searchable_task)
        searchable_task.state = TaskState.DASHBOARD_READY.value
        searchable_task.next_card = CardId.ADJUSTMENT.value
        db.add(searchable_task)
        db.commit()

    assert db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='years').count() == 1
    assert db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='years').one().value['from_year'] == 2019
    assert db.query(TaskJob).filter_by(task_id=searchable_task.id, kind='search').count() == 1
    assert db.query(TaskEvent).filter_by(task_id=searchable_task.id, event_type='answer_revised').count() == 2


def test_multi_card_adjustment_follows_mode_term_year_order(db, searchable_task, owner):
    answer_card(
        searchable_task.id,
        CardId.ADJUSTMENT,
        {'adjustment': ['years', 'terms']},
        owner,
    )
    terms = answer_card(
        searchable_task.id,
        CardId.TERMS,
        {'terms': ['drainage resilience']},
        owner,
    )
    assert terms.next_card == CardId.YEARS
    assert terms.job_id is None

    years = answer_card(
        searchable_task.id,
        CardId.YEARS,
        {'choice': 'C', 'from_year': 2016},
        owner,
    )
    assert years.state == TaskState.SEARCHING
    assert years.next_card is None
    assert years.job_id is not None


def test_unknown_adjustment_is_not_silently_treated_as_continue(db, searchable_task, owner):
    with pytest.raises(HTTPException) as exc_info:
        answer_card(
            searchable_task.id,
            CardId.ADJUSTMENT,
            {'adjustment': ['unexpected']},
            owner,
        )

    assert exc_info.value.status_code == 422
    assert db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='adjustment').count() == 0
    assert db.query(TaskEvent).filter_by(task_id=searchable_task.id).count() == 0


def test_mode_revision_reloads_template_and_uses_existing_c_results(db, searchable_task, owner):
    mode_answer = db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='mode').one()
    mode_answer.value = {'mode': 'A', 'user_results': 'The intervention reduced readmissions.'}
    db.add(mode_answer)
    db.commit()

    answer_card(
        searchable_task.id,
        CardId.ADJUSTMENT,
        {'adjustment': ['mode']},
        owner,
    )
    revised = answer_card(
        searchable_task.id,
        CardId.MODE,
        {'mode': 'C'},
        owner,
    )

    assert revised.state == TaskState.DASHBOARD_READY
    assert revised.next_card == CardId.ADJUSTMENT
    event = db.query(TaskEvent).filter_by(task_id=searchable_task.id, event_type='answer_revised').one()
    assert event.payload['follow_up'] is None
    assert event.payload['mode_template'] == 'C'


def test_continue_freezes_settings_and_no_later_card_can_restart_questions(db, searchable_task, owner):
    answer_card(
        searchable_task.id,
        CardId.ADJUSTMENT,
        {'adjustment': ['continue', 'terms']},
        owner,
    )
    delivery = answer_card(searchable_task.id, CardId.DELIVERY, {'form': 'B'}, owner)
    assert delivery.state == TaskState.GENERATING

    terms_before = db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='terms').one().value
    with pytest.raises(HTTPException) as exc_info:
        answer_card(
            searchable_task.id,
            CardId.TERMS,
            {'terms': ['must not reopen']},
            owner,
        )
    assert exc_info.value.status_code == 409
    assert db.query(TaskAnswer).filter_by(task_id=searchable_task.id, card_id='terms').one().value == terms_before
    assert db.query(TaskEvent).filter_by(task_id=searchable_task.id, event_type='answer_conflict').count() == 0
