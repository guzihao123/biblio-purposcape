"""Both local and sites payloads expose the same progress.percent contract."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskProgress
from app.task_presenters import remote_task_payload, task_payload


@pytest.fixture
def db():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def task(db):
    owner = InviteSession(id=str(uuid4()))
    record = Task(
        id=str(uuid4()),
        session_id=owner.id,
        state='searching',
        next_card=None,
    )
    db.add_all([owner, record])
    db.commit()
    return record


def test_task_payload_includes_percent_from_task_progress(db, task):
    db.add(TaskProgress(
        task_id=task.id,
        stage='search',
        message='正在生成图谱',
        percent=80,
    ))
    db.commit()
    db.refresh(task)

    payload = task_payload(db, task)
    assert payload['progress']['stage'] == 'search'
    assert payload['progress']['message'] == '正在生成图谱'
    assert payload['progress']['percent'] == 80
    assert payload['progress']['checkpoint'] is None


def test_task_payload_defaults_percent_to_zero_on_legacy_row(db, task):
    progress = TaskProgress(task_id=task.id, stage='search', message='旧进度')
    db.add(progress)
    db.commit()
    db.expire(task, ['progress'])

    payload = task_payload(db, task)
    assert payload['progress']['percent'] == 0


def test_remote_task_payload_includes_percent(db):
    aggregate = {
        'id': 'remote-task',
        'session_id': 'remote-session',
        'state': 'generating',
        'next_card': None,
        'answers': {},
        'progress': {
            'stage': 'generate',
            'message': '正在生成正文',
            'percent': 55,
            'checkpoint': None,
        },
    }
    payload = remote_task_payload(db, aggregate)
    assert payload['progress']['stage'] == 'generate'
    assert payload['progress']['message'] == '正在生成正文'
    assert payload['progress']['percent'] == 55
    assert payload['progress']['checkpoint'] is None


def test_remote_task_payload_defaults_to_zero_without_percent(db):
    aggregate = {
        'id': 'remote-legacy',
        'session_id': 'remote-session',
        'state': 'searching',
        'next_card': None,
        'answers': {},
        'progress': {'stage': 'search', 'message': '旧进度'},
    }
    payload = remote_task_payload(db, aggregate)
    assert payload['progress']['percent'] == 0
