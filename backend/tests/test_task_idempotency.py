from datetime import datetime, timezone
from threading import Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db, initialize_database
from app.main import app
from app.models import Base, InviteSession, SkillVersion, Task
from app.rate_limit import RateLimitRule


@pytest.fixture
def api_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'idempotency.db'
    engine = create_engine(
        f'sqlite:///{database_path}',
        connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv('SESSION_SECRET', 'idempotency-test-secret')
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()
    engine.dispose()


@pytest.fixture
def published_version(api_database):
    with api_database() as db:
        version = SkillVersion(
            id='published-version',
            version=1,
            state='published',
            content={'cards': {}},
            content_hash='version-hash',
            created_at=datetime.now(timezone.utc),
        )
        db.add(version)
        db.commit()
        return version.id


def create_session():
    client = TestClient(app, base_url='https://testserver')
    response = client.post('/api/session', json={})
    assert response.status_code == 201
    return {
        'id': response.json()['session_id'],
        'cookie': response.headers['set-cookie'].split(';', 1)[0],
    }


def post_task(session, key):
    headers = {'Cookie': session['cookie']}
    if key is not None:
        headers['Idempotency-Key'] = key
    client = TestClient(app, base_url='https://testserver')
    return client.post('/api/tasks', json={}, headers=headers)


def counter_values(limiter, operation):
    return sorted(
        int(limiter.connection.get(key))
        for key in limiter.connection.keys(f'*{operation}*')
    )


def test_concurrent_api_retries_create_one_task_and_consume_quota_once(
    api_database, published_version, isolated_rate_limiter
):
    session = create_session()
    isolated_rate_limiter.rules = {
        'session_create': {'ip': RateLimitRule(100, 3600)},
        'task_create': {
            'session': RateLimitRule(100, 86400),
            'ip': RateLimitRule(100, 86400),
        },
    }
    responses = []
    errors = []

    def create():
        try:
            responses.append(post_task(session, 'same-concurrent-key'))
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=create) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert [response.status_code for response in responses] == [201] * 8
    payloads = [response.json() for response in responses]
    assert len({payload['id'] for payload in payloads}) == 1
    assert {payload['skill_version_id'] for payload in payloads} == {published_version}

    with api_database() as db:
        tasks = db.query(Task).filter_by(session_id=session['id']).all()
        assert len(tasks) == 1
        assert tasks[0].id == payloads[0]['id']
        assert tasks[0].idempotency_key == 'same-concurrent-key'
        assert tasks[0].skill_version_id == published_version
        assert db.query(SkillVersion).count() == 1

    # One session counter and one IP counter, each charged exactly once.
    assert counter_values(isolated_rate_limiter, 'task_create') == [1, 1]


def test_retry_after_restart_returns_database_task_without_quota_consumption(
    api_database, published_version, isolated_rate_limiter
):
    session = create_session()
    first = post_task(session, 'restart-stable-key')
    assert first.status_code == 201

    # Simulate a new process with empty Redis idempotency state. The database is
    # authoritative, so the retry must not need another quota reservation.
    isolated_rate_limiter.connection.flushdb()
    with TestClient(app, base_url='https://testserver') as restarted_client:
        retry = restarted_client.post(
            '/api/tasks',
            json={},
            headers={
                'Cookie': session['cookie'],
                'Idempotency-Key': 'restart-stable-key',
            },
        )

    assert retry.status_code == 201
    assert retry.json()['id'] == first.json()['id']
    assert retry.json()['skill_version_id'] == first.json()['skill_version_id']
    assert counter_values(isolated_rate_limiter, 'task_create') == []
    with api_database() as db:
        assert db.query(Task).filter_by(session_id=session['id']).count() == 1


def test_same_empty_body_with_different_keys_is_a_legitimate_new_research(
    api_database, published_version, isolated_rate_limiter
):
    session = create_session()
    first = post_task(session, 'deliberate-new-1')
    second = post_task(session, 'deliberate-new-2')

    assert first.status_code == second.status_code == 201
    assert first.json()['id'] != second.json()['id']
    with api_database() as db:
        assert db.query(Task).filter_by(session_id=session['id']).count() == 2


def test_same_key_is_isolated_between_sessions(
    api_database, published_version, isolated_rate_limiter
):
    isolated_rate_limiter.rules = {
        'session_create': {'ip': RateLimitRule(100, 3600)},
        'task_create': {
            'session': RateLimitRule(1, 86400),
            'ip': RateLimitRule(100, 86400),
        },
    }
    first_session = create_session()
    second_session = create_session()

    first = post_task(first_session, 'shared-client-key')
    second = post_task(second_session, 'shared-client-key')

    assert first.status_code == second.status_code == 201
    assert first.json()['id'] != second.json()['id']
    with api_database() as db:
        assert db.query(Task).count() == 2


def test_task_rate_limit_returns_safe_429_and_retry_after(
    api_database, published_version, isolated_rate_limiter
):
    isolated_rate_limiter.clock = lambda: 0
    isolated_rate_limiter.rules = {
        'session_create': {'ip': RateLimitRule(100, 3600)},
        'task_create': {
            'session': RateLimitRule(1, 60),
            'ip': RateLimitRule(100, 60),
        },
    }
    session = create_session()
    first = post_task(session, 'within-quota')
    assert first.status_code == 201

    denied = post_task(session, 'over-quota')

    assert denied.status_code == 429
    assert denied.headers['Retry-After'] == '60'
    assert denied.json()['detail'] == {
        'code': 'rate_limited',
        'message': '请求过于频繁，请稍后重试。',
        'retry_after': 60,
    }
    assert 'traceback' not in denied.text.lower()
    assert 'redis' not in denied.text.lower()
    assert '/Users/' not in denied.text

    # Retrying the original key is an idempotent read, not a new quota request.
    replay = post_task(session, 'within-quota')
    assert replay.status_code == 201
    assert replay.json()['id'] == first.json()['id']
    assert counter_values(isolated_rate_limiter, 'task_create') == [1, 1]


def test_session_rate_limit_prevents_second_row_and_cookie(
    api_database, isolated_rate_limiter
):
    isolated_rate_limiter.clock = lambda: 0
    isolated_rate_limiter.rules = {
        'session_create': {'ip': RateLimitRule(1, 60)},
    }
    first = TestClient(app, base_url='https://testserver').post('/api/session')
    assert first.status_code == 201

    denied = TestClient(app, base_url='https://testserver').post('/api/session')

    assert denied.status_code == 429
    assert denied.headers['Retry-After'] == '60'
    assert 'set-cookie' not in denied.headers
    with api_database() as db:
        assert db.query(InviteSession).count() == 1


def test_legacy_migration_preserves_versions_timestamps_and_null_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-idempotency.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE invite_sessions (id VARCHAR(36) PRIMARY KEY)'))
            connection.execute(text('''
                CREATE TABLE tasks (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    skill_version_id VARCHAR(36),
                    created_at DATETIME,
                    updated_at DATETIME,
                    idempotency_key VARCHAR(255)
                )
            '''))
            connection.execute(text("INSERT INTO invite_sessions (id) VALUES ('legacy-owner')"))
            connection.execute(text("""
                INSERT INTO tasks (
                    id, session_id, skill_version_id, created_at, updated_at, idempotency_key
                ) VALUES
                    ('legacy-null', 'legacy-owner', 'version-old', '2024-01-01', '2024-01-02', NULL),
                    ('legacy-empty', 'legacy-owner', 'version-old', '2024-02-01', '2024-02-02', '')
            """))

        initialize_database(engine)

        with engine.begin() as connection:
            rows = connection.execute(text(
                'SELECT id, skill_version_id, created_at, updated_at, idempotency_key '
                'FROM tasks ORDER BY id'
            )).all()
            assert len(rows) == 2
            assert {row[1] for row in rows} == {'version-old'}
            assert {row[2] for row in rows} == {'2024-01-01', '2024-02-01'}
            assert {row[3] for row in rows} == {'2024-01-02', '2024-02-02'}
            assert {row[4] for row in rows} == {None}
            indexes = connection.execute(text("PRAGMA index_list('tasks')")).all()
            assert any(row[1] == 'uq_tasks_session_idempotency_key' and row[2] for row in indexes)
    finally:
        engine.dispose()
