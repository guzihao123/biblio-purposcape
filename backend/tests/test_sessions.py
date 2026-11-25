import hashlib
import hmac
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app


INVITE_CODE = 'valid-code'


@pytest.fixture(autouse=True)
def configure_security(monkeypatch):
    monkeypatch.setenv('INVITE_CODE_HASH', hashlib.sha256(INVITE_CODE.encode()).hexdigest())
    monkeypatch.setenv('SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('ADMIN_TOKEN', 'test-admin-token')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def database():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
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


@pytest.fixture
def two_sessions(database):
    def create_session():
        session_client = TestClient(app, base_url='https://testserver')
        response = session_client.post('/api/session', json={'invite_code': INVITE_CODE})
        assert response.status_code == 201
        return SimpleNamespace(
            id=response.json()['session_id'],
            headers={'Cookie': response.headers['set-cookie'].split(';', 1)[0]},
        )

    return SimpleNamespace(first=create_session(), second=create_session())


@pytest.fixture
def task_factory(database):
    def create_task(owner):
        database.ensure_schema()
        from app.models import Task

        with database.session_factory() as db:
            task = Task(id=str(uuid4()), session_id=owner.id)
            db.add(task)
            db.commit()
            db.refresh(task)
            return task

    return create_task


def test_invite_code_creates_http_only_session(client):
    response = client.post('/api/session', json={'invite_code': 'valid-code'})
    assert response.status_code == 201

    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie
    assert 'Secure' in cookie
    assert 'SameSite=lax' in cookie
    assert response.json()['session_id']

    from itsdangerous import BadSignature, URLSafeSerializer

    signed_session = client.cookies.get('invite_session')
    assert signed_session != response.json()['session_id']
    assert URLSafeSerializer('test-session-secret').loads(signed_session) == response.json()['session_id']
    with pytest.raises(BadSignature):
        URLSafeSerializer('wrong-secret').loads(signed_session)


def test_public_session_does_not_require_invite_code(client):
    response = client.post('/api/session', json={})
    assert response.status_code == 201
    assert response.json()['session_id']
    assert 'set-cookie' in response.headers


def test_session_cannot_read_another_sessions_task(client, two_sessions, task_factory):
    first = two_sessions.first
    second = two_sessions.second
    task = task_factory(owner=first)
    response = client.get(f'/api/tasks/{task.id}', headers=second.headers)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Task not found'}

    missing = client.get('/api/tasks/does-not-exist', headers=second.headers)
    assert missing.status_code == response.status_code
    assert missing.json() == response.json()


def test_session_can_read_its_own_task(client, two_sessions, task_factory):
    first = two_sessions.first
    task = task_factory(owner=first)
    response = client.get(f'/api/tasks/{task.id}', headers=first.headers)
    assert response.status_code == 200
    assert response.json()['id'] == task.id


def test_missing_and_tampered_sessions_are_rejected(client, two_sessions, task_factory):
    first = two_sessions.first
    task = task_factory(owner=first)

    missing = client.get(f'/api/tasks/{task.id}')
    assert missing.status_code == 401
    assert missing.json() == {'detail': 'Invalid session'}

    tampered = client.get(
        f'/api/tasks/{task.id}',
        headers={'Cookie': f'{first.headers["Cookie"]}tampered'},
    )
    assert tampered.status_code == 401
    assert tampered.json() == {'detail': 'Invalid session'}


def test_admin_requires_the_separate_admin_token():
    from app.security import require_admin

    for token in ('', 'wrong-token', 'test-session-secret'):
        with pytest.raises(HTTPException) as exc_info:
            require_admin(token)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == 'Admin access required'

    assert require_admin('test-admin-token') is None


def test_admin_secret_uses_constant_time_comparison(client, monkeypatch):
    import app.security as security

    comparisons = []
    real_compare_digest = hmac.compare_digest

    def recording_compare_digest(first, second):
        comparisons.append((first, second))
        return real_compare_digest(first, second)

    monkeypatch.setattr(security.hmac, 'compare_digest', recording_compare_digest)

    response = client.post('/api/session', json={'invite_code': INVITE_CODE})
    assert response.status_code == 201
    security.require_admin('test-admin-token')

    assert comparisons == [
        (b'test-admin-token', b'test-admin-token'),
    ]


def test_session_ownership_does_not_follow_proxy_ip(client, database, two_sessions, task_factory):
    from app.models import InviteSession

    first = two_sessions.first
    second = two_sessions.second
    task = task_factory(owner=first)
    with database.session_factory() as db:
        for session_id in (first.id, second.id):
            record = db.get(InviteSession, session_id)
            record.client_ip = '203.0.113.99'
        db.commit()

    forwarded = {'X-Forwarded-For': '198.51.100.25'}
    own = client.get(f'/api/tasks/{task.id}', headers={**first.headers, **forwarded})
    other = client.get(f'/api/tasks/{task.id}', headers={**second.headers, **forwarded})

    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json() == {'detail': 'Task not found'}


def test_revoke_session_service_is_persistent_and_idempotent(client, database):
    from app.security import revoke_session

    response = client.post('/api/session', json={})
    assert response.status_code == 201
    session_id = response.json()['session_id']
    cookie = {'Cookie': response.headers['set-cookie'].split(';', 1)[0]}

    with database.session_factory() as db:
        revoked = revoke_session(db, session_id)
        revoked_at = revoked.revoked_at
        assert revoked_at is not None
        assert revoke_session(db, session_id).revoked_at == revoked_at
        with pytest.raises(HTTPException) as exc_info:
            revoke_session(db, 'does-not-exist')
        assert exc_info.value.status_code == 404

    denied = client.get('/api/tasks', headers=cookie)
    assert denied.status_code == 401
    assert denied.json() == {'detail': 'Invalid session'}


def test_admin_revoke_route_requires_admin_and_hides_session_existence(
    client,
    database,
    two_sessions,
):
    from app.models import InviteSession

    target_id = two_sessions.first.id
    callers = (
        {},
        {'X-Admin-Token': 'wrong-token'},
        two_sessions.first.headers,
    )
    for headers in callers:
        for session_id in (target_id, 'does-not-exist'):
            response = client.post(
                f'/api/admin/sessions/{session_id}/revoke',
                headers=headers,
            )
            assert response.status_code == 403
            assert response.json() == {'detail': 'Admin access required'}

    with database.session_factory() as db:
        assert db.get(InviteSession, target_id).revoked_at is None

    missing = client.post(
        '/api/admin/sessions/does-not-exist/revoke',
        headers={'X-Admin-Token': 'test-admin-token'},
    )
    assert missing.status_code == 404
    assert missing.json() == {'detail': 'Session not found'}
    assert 'does-not-exist' not in missing.text
    assert 'set-cookie' not in missing.headers


def test_admin_revoke_route_blocks_access_is_idempotent_and_preserves_other_sessions(
    client,
    database,
    two_sessions,
    task_factory,
    tmp_path,
    monkeypatch,
    caplog,
):
    from app.models import InviteSession, Task, TaskAnswer

    monkeypatch.setenv('ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    get_settings.cache_clear()
    first = two_sessions.first
    second = two_sessions.second
    first_task = task_factory(owner=first)
    second_task = task_factory(owner=second)
    artifact_dir = tmp_path / 'artifacts' / first_task.id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / 'report.docx').write_bytes(b'PK-admin-revoke')
    listing = client.get(f'/api/tasks/{first_task.id}/artifacts', headers=first.headers)
    assert listing.status_code == 200
    artifact_url = next(
        item['url'] for item in listing.json()['artifacts'] if item['name'] == 'report.docx'
    )

    route = f'/api/admin/sessions/{first.id}/revoke'
    admin_headers = {'X-Admin-Token': 'test-admin-token'}
    success = client.post(route, headers=admin_headers)
    assert success.status_code == 200
    assert success.json() == {'revoked': True}
    assert 'set-cookie' not in success.headers

    with database.session_factory() as db:
        revoked_at = db.get(InviteSession, first.id).revoked_at
        assert revoked_at is not None

    denied_requests = (
        client.post('/api/tasks', json={}, headers=first.headers),
        client.post(
            f'/api/tasks/{first_task.id}/answers/direction',
            json={'value': {'direction': '撤销后不应写入'}},
            headers=first.headers,
        ),
        client.get('/api/tasks', headers=first.headers),
        client.get(f'/api/tasks/{first_task.id}/report', headers=first.headers),
        client.get(artifact_url, headers=first.headers),
    )
    for response in denied_requests:
        assert response.status_code == 401
        assert response.json() == {'detail': 'Invalid session'}

    other_task = client.get(f'/api/tasks/{second_task.id}', headers=second.headers)
    other_history = client.get('/api/tasks', headers=second.headers)
    assert other_task.status_code == 200
    assert other_task.json()['id'] == second_task.id
    assert [item['id'] for item in other_history.json()['tasks']] == [second_task.id]

    repeat = client.post(route, headers=admin_headers)
    assert repeat.status_code == 200
    assert repeat.json() == {'revoked': True}
    assert 'set-cookie' not in repeat.headers
    with database.session_factory() as db:
        assert db.get(InviteSession, first.id).revoked_at == revoked_at
        assert db.get(InviteSession, second.id).revoked_at is None
        assert db.query(Task).count() == 2
        assert db.query(TaskAnswer).count() == 0

    cookie_header = first.headers['Cookie']
    signed_session = cookie_header.split('invite_session=', 1)[1]
    for response in (success, repeat):
        observable = response.text + '\n' + str(response.headers)
        assert 'test-admin-token' not in observable
        assert cookie_header not in observable
        assert signed_session not in observable
        assert 'client_ip' not in observable
        assert 'user_agent' not in observable
    assert 'test-admin-token' not in caplog.text
    assert cookie_header not in caplog.text
    assert signed_session not in caplog.text


def test_non_ascii_admin_token_never_causes_500(client):
    response = client.get('/api/admin/skill/versions', headers={'X-Admin-Token': '错误令牌'.encode('utf-8')})
    assert response.status_code == 403, response.text
    assert response.json() == {'detail': 'Admin access required'}

    get_settings().admin_token = '有效管理员令牌'
    accepted = client.get('/api/admin/skill/versions', headers={'X-Admin-Token': '有效管理员令牌'.encode('utf-8')})
    assert accepted.status_code == 200, accepted.text
