from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app


@pytest.fixture(autouse=True)
def configure_security(monkeypatch):
    monkeypatch.setenv('SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('ADMIN_TOKEN', 'test-admin-token')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def database():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def ensure_schema():
        from app.models import Base
        Base.metadata.create_all(bind=engine)

    def override_get_db():
        ensure_schema()
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield SimpleNamespace(ensure_schema=ensure_schema, session_factory=session_factory)
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def client(database):
    return TestClient(app, base_url='https://testserver')


def create_public_session():
    session_client = TestClient(app, base_url='https://testserver')
    response = session_client.post('/api/session', json={})
    assert response.status_code == 201
    return SimpleNamespace(
        id=response.json()['session_id'],
        headers={'Cookie': response.headers['set-cookie'].split(';', 1)[0]},
    )


def test_public_session_requires_no_invite_code(client):
    response = client.post('/api/session', json={})
    assert response.status_code == 201
    assert response.json()['session_id']
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie
    assert 'Secure' in cookie
    assert 'SameSite=lax' in cookie
    assert response.json()['session_id'] != client.cookies.get('invite_session')


def test_public_session_empty_body_is_accepted(client):
    response = client.post('/api/session')
    assert response.status_code == 201
    assert response.json()['session_id']


def test_public_session_records_quota_metadata(client, database):
    response = client.post('/api/session', json={}, headers={'User-Agent': 'competition-test-agent'})
    assert response.status_code == 201
    from app.models import InviteSession
    with database.session_factory() as db:
        record = db.get(InviteSession, response.json()['session_id'])
        assert record.client_ip == 'testclient'
        assert record.user_agent == 'competition-test-agent'


def test_public_users_cannot_read_each_others_tasks(client, database):
    first = create_public_session()
    second = create_public_session()
    from app.models import Task
    with database.session_factory() as db:
        task = Task(id=str(uuid4()), session_id=first.id)
        db.add(task)
        db.commit()
        task_id = task.id
    response = client.get(f'/api/tasks/{task_id}', headers=second.headers)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Task not found'}


def test_legacy_invite_sessions_upgrade_preserves_owner_and_tasks(tmp_path):
    from sqlalchemy import text
    from app.db import initialize_database

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-public.db'}", connect_args={'check_same_thread': False})
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE invite_sessions (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL)'))
        connection.execute(text("INSERT INTO invite_sessions (id) VALUES ('legacy-session')"))
        connection.execute(text("INSERT INTO tasks (id, session_id) VALUES ('legacy-task', 'legacy-session')"))

    initialize_database(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(invite_sessions)'))}
        assert {'id', 'client_ip', 'user_agent'} <= columns
        owner = connection.execute(text("SELECT id FROM invite_sessions WHERE id='legacy-session'")).scalar()
        task = connection.execute(text("SELECT id FROM tasks WHERE id='legacy-task'")).scalar()
        assert owner == 'legacy-session'
        assert task == 'legacy-task'
    engine.dispose()


def test_public_session_has_absolute_server_expiry(client, database):
    from datetime import datetime, timedelta, timezone
    from app.models import InviteSession

    before = datetime.now(timezone.utc)
    response = client.post('/api/session', json={})
    after = datetime.now(timezone.utc)
    assert response.status_code == 201

    with database.session_factory() as db:
        record = db.get(InviteSession, response.json()['session_id'])
        stored_expiry = record.expires_at
        assert stored_expiry is not None
        assert record.revoked_at is None
    expires_at = stored_expiry
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    ttl = timedelta(seconds=get_settings().session_ttl_seconds)
    assert before + ttl <= expires_at <= after + ttl

    assert client.get('/api/tasks').status_code == 200
    with database.session_factory() as db:
        record = db.get(InviteSession, response.json()['session_id'])
        assert record.expires_at == stored_expiry


def test_legacy_session_security_migration_is_repeatable_and_non_destructive(tmp_path):
    from sqlalchemy import text
    from app.db import initialize_database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-session-security.db'}",
        connect_args={'check_same_thread': False},
    )
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE invite_sessions (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL)'))
        connection.execute(text("INSERT INTO invite_sessions (id) VALUES ('legacy-session')"))
        connection.execute(text("INSERT INTO tasks (id, session_id) VALUES ('legacy-task', 'legacy-session')"))

    initialize_database(bind=engine)
    with engine.begin() as connection:
        first_expiry = connection.execute(
            text("SELECT expires_at FROM invite_sessions WHERE id='legacy-session'")
        ).scalar()

    initialize_database(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(invite_sessions)'))}
        assert {'expires_at', 'revoked_at'} <= columns
        row = connection.execute(
            text(
                "SELECT id, expires_at, revoked_at FROM invite_sessions "
                "WHERE id='legacy-session'"
            )
        ).one()
        assert row[0] == 'legacy-session'
        assert row[1] is not None
        assert row[1] == first_expiry
        assert row[2] is None
        assert connection.execute(
            text("SELECT id FROM tasks WHERE id='legacy-task'")
        ).scalar() == 'legacy-task'
    engine.dispose()
