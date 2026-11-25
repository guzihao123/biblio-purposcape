from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    InviteSession,
    Task,
    TaskAnswer,
    TaskEvent,
    TaskJob,
)
from app.task_expiry import (
    EXPIRABLE_TASK_STATES,
    EXPIRED_EVENT_TYPE,
    EXPIRED_REASON,
    expire_idle_collection_tasks,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


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


def make_task(db, state, updated_at, with_answer=False):
    owner = InviteSession(id=str(uuid4()))
    db.add(owner)
    task = Task(
        id=str(uuid4()),
        session_id=owner.id,
        state=state,
        next_card='terms',
    )
    db.add(task)
    db.flush()
    if with_answer:
        db.add(TaskAnswer(
            task_id=task.id,
            card_id='mode',
            value={'mode': 'offline'},
            result_state='collecting_terms',
            next_card='terms',
        ))
    db.commit()
    # Bypass the ORM onupdate so the simulated idle time is exact.
    db.execute(
        text('UPDATE tasks SET updated_at = :ts WHERE id = :id'),
        {'ts': updated_at, 'id': task.id},
    )
    db.commit()
    return task


def events(db, task_id):
    return db.query(TaskEvent).filter_by(task_id=task_id).order_by(TaskEvent.id).all()


def test_stale_collection_tasks_expire_to_error_with_safety_reason_and_no_compute(session_factory):
    with session_factory() as db:
        stale = [
            make_task(db, state, (NOW - timedelta(hours=25)).isoformat(), with_answer=True)
            for state in EXPIRABLE_TASK_STATES
        ]

        results = expire_idle_collection_tasks(
            session_factory=session_factory,
            now=lambda: NOW,
            idle_hours=24,
        )

        assert sorted(item['previous_state'] for item in results) == sorted(EXPIRABLE_TASK_STATES)
        assert all(item['reason'] == EXPIRED_REASON for item in results)
        by_id = {item['task_id']: item for item in results}
        for task in stale:
            result = by_id[task.id]
            db.refresh(task)
            assert task.state == 'error'
            assert task.next_card == 'terms'  # no answer data discarded
            assert db.query(TaskAnswer).filter_by(task_id=task.id).count() == 1
            assert db.query(TaskJob).filter_by(task_id=task.id).count() == 0
            recorded = events(db, task.id)
            assert len(recorded) == 1
            assert recorded[0].event_type == EXPIRED_EVENT_TYPE
            assert recorded[0].payload['category'] == 'safety'
            assert recorded[0].payload['reason'] == EXPIRED_REASON
            assert recorded[0].payload['state'] == 'error'
            assert recorded[0].payload['previous_state'] == result['previous_state']
            assert recorded[0].payload['compute_charged'] is False
            assert recorded[0].payload['data_deleted'] is False
            assert db.query(TaskEvent).filter(
                TaskEvent.task_id == task.id,
                TaskEvent.event_type.in_(['rate_limited', 'retry_scheduled']),
            ).count() == 0


def test_fresh_collection_and_all_non_collection_states_are_untouched(session_factory):
    with session_factory() as db:
        fresh = make_task(db, 'collecting_mode', (NOW - timedelta(hours=23)).isoformat())
        other_states = [
            'searching', 'dashboard_ready', 'adjusting', 'delivery_confirmed',
            'generating', 'verifying', 'done', 'error',
        ]
        others = [
            make_task(db, state, (NOW - timedelta(days=5)).isoformat())
            for state in other_states
        ]

        results = expire_idle_collection_tasks(
            session_factory=session_factory,
            now=lambda: NOW,
            idle_hours=24,
        )

        assert results == []
        db.refresh(fresh)
        assert fresh.state == 'collecting_mode'
        for task in others:
            db.refresh(task)
            assert task.state in other_states
        assert db.query(TaskEvent).count() == 0


def test_dry_run_lists_candidates_without_writing(session_factory):
    with session_factory() as db:
        task = make_task(db, 'collecting_terms', (NOW - timedelta(hours=30)).isoformat())
        original_updated_at = task.updated_at

        results = expire_idle_collection_tasks(
            session_factory=session_factory,
            now=lambda: NOW,
            idle_hours=24,
            dry_run=True,
        )

        assert len(results) == 1
        assert results[0]['task_id'] == task.id
        assert results[0]['dry_run'] is True
        assert results[0]['previous_state'] == 'collecting_terms'
        assert results[0]['idle_seconds'] == 30 * 3600
        db.refresh(task)
        assert task.state == 'collecting_terms'
        assert task.updated_at == original_updated_at
        assert events(db, task.id) == []


def test_second_sweep_is_idempotent(session_factory):
    with session_factory() as db:
        task = make_task(db, 'collecting_years', (NOW - timedelta(hours=48)).isoformat())
        options = dict(session_factory=session_factory, now=lambda: NOW, idle_hours=24)

        first = expire_idle_collection_tasks(**options)
        second = expire_idle_collection_tasks(**options)

        assert len(first) == 1
        assert second == []
        db.refresh(task)
        assert task.state == 'error'
        assert len(events(db, task.id)) == 1


def test_threshold_is_configurable_and_legacy_naive_timestamps_are_supported(session_factory):
    with session_factory() as db:
        stale = make_task(
            db, 'collecting_mode',
            (NOW - timedelta(hours=8)).replace(tzinfo=None),
        )
        recent = make_task(db, 'collecting_mode', (NOW - timedelta(hours=2)).isoformat())

        results = expire_idle_collection_tasks(
            session_factory=session_factory,
            now=lambda: NOW,
            idle_hours=6,
        )

        assert [item['task_id'] for item in results] == [stale.id]
        db.refresh(stale)
        db.refresh(recent)
        assert stale.state == 'error'
        assert recent.state == 'collecting_mode'

        with pytest.raises(ValueError, match='positive'):
            expire_idle_collection_tasks(
                session_factory=session_factory, now=lambda: NOW, idle_hours=0,
            )


def test_default_threshold_comes_from_environment(monkeypatch, session_factory):
    monkeypatch.setenv('TASK_EXPIRY_HOURS', '2')
    with session_factory() as db:
        stale = make_task(db, 'collecting_mode', (NOW - timedelta(hours=3)).isoformat())

        results = expire_idle_collection_tasks(
            session_factory=session_factory, now=lambda: NOW,
        )

        assert [item['task_id'] for item in results] == [stale.id]

        monkeypatch.setenv('TASK_EXPIRY_HOURS', '0')
        with pytest.raises(ValueError, match='TASK_EXPIRY_HOURS'):
            expire_idle_collection_tasks(
                session_factory=session_factory, now=lambda: NOW,
            )


def test_recovery_cycle_runs_expiry_in_both_store_modes(monkeypatch, session_factory):
    from app import recovery

    calls = []
    monkeypatch.setattr(
        recovery,
        'expire_idle_collection_tasks',
        lambda **kwargs: calls.append(kwargs) or [{'task_id': 'expired-1'}],
    )
    monkeypatch.setattr(recovery, 'recover_interrupted_tasks', lambda **kwargs: [])
    monkeypatch.setattr(recovery, 'schedule_due_retries', lambda **kwargs: [])
    monkeypatch.setattr(
        'app.config.get_settings',
        lambda: SimpleNamespace(task_store_authority='local'),
    )

    cycle = recovery.run_recovery_cycle(now=lambda: NOW, session_factory=session_factory)
    assert cycle['expired'] == [{'task_id': 'expired-1'}]
    assert calls[-1]['session_factory'] is session_factory

    monkeypatch.setattr(
        'app.config.get_settings',
        lambda: SimpleNamespace(task_store_authority='sites'),
    )
    monkeypatch.setattr(
        'app.remote_recovery.run_remote_recovery_cycle',
        lambda **kwargs: {'recovered': [], 'requeued': []},
    )
    cycle = recovery.run_recovery_cycle(now=lambda: NOW, session_factory=session_factory)
    assert cycle['expired'] == [{'task_id': 'expired-1'}]


def test_cli_dry_run_prints_candidates_and_passes_dry_run(monkeypatch, capsys):
    from app import task_expiry_cli

    seen = {}

    def fake_expire(**kwargs):
        seen.update(kwargs)
        return [{'task_id': 'candidate-1'}]

    monkeypatch.setattr(task_expiry_cli, 'expire_idle_collection_tasks', fake_expire)
    monkeypatch.setattr(task_expiry_cli, 'configured_idle_hours', lambda: 24)

    assert task_expiry_cli.main(['--dry-run', '--hours', '6']) == 0
    assert seen == {'idle_hours': 6.0, 'dry_run': True}
    payload = capsys.readouterr().out
    assert '"dry_run": true' in payload
    assert 'candidate-1' in payload
