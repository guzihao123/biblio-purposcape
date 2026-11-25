from pathlib import Path
from uuid import uuid4
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Base, InviteSession, Task
from app.skill_versions import SkillVersionService, load_base_config


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
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv('SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    get_settings.cache_clear()
    calls = []

    class FakeQueue:
        def enqueue_stage(self, task_id, stage):
            from app.models import TaskProgress

            calls.append((task_id, stage))
            progress = db.get(TaskProgress, task_id) or TaskProgress(task_id=task_id)
            progress.stage = stage
            progress.message = f'queued:{stage}'
            db.add(progress)
            db.commit()
            return {'id': f'rq-{stage}'}

    monkeypatch.setattr('app.main.queue_adapter', FakeQueue())
    monkeypatch.setattr('app.main.candidate_service', type('FakeCandidates', (), {
        'generate': lambda self, direction, mode: [],
    })())

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app, base_url='https://testserver')
    test_client.queue_calls = calls
    yield test_client
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def publish_base(db):
    service = SkillVersionService(db)
    draft = service.create_draft(None, load_base_config(), actor='test-admin')
    service.run_regression(draft.id, lambda config: {'passed': True}, actor='test-admin')
    return service.publish(draft.id, actor='test-admin')


def create_session(client):
    response = client.post('/api/session', json={})
    assert response.status_code == 201
    return response.json()['session_id']


def test_create_read_and_history_use_owner_and_pinned_version(client, db):
    version = publish_base(db)
    session_id = create_session(client)

    created = client.post('/api/tasks', json={})
    assert created.status_code == 201
    payload = created.json()
    assert payload['skill_version_id'] == version.id
    assert payload['next_card'] == 'direction'
    assert payload['card']['id'] == 'direction'
    assert payload['created_at']

    other = InviteSession(id=str(uuid4()))
    db.add(other)
    db.add(Task(id='other-task', session_id=other.id))
    db.commit()
    history = client.get('/api/tasks')
    assert history.status_code == 200
    assert [item['id'] for item in history.json()['tasks']] == [payload['id']]
    assert history.json()['tasks'][0]['session_id'] == session_id


def test_task_creation_requires_a_published_version(client):
    create_session(client)
    response = client.post('/api/tasks', json={})
    assert response.status_code == 409
    assert 'published' in response.json()['detail']


def test_answers_advance_real_cards_and_enqueue_search_once(client, db):
    publish_base(db)
    create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']

    direction = client.post(f'/api/tasks/{task_id}/answers/direction', json={'value': {'direction': '城市内涝'}})
    assert direction.status_code == 200
    assert direction.json()['next_card'] == 'mode'

    mode = client.post(f'/api/tasks/{task_id}/answers/mode', json={'value': {'mode': 'A'}})
    assert mode.json()['next_card'] == 'terms'
    assert mode.json()['card']['id'] == 'terms'

    terms = client.post(f'/api/tasks/{task_id}/answers/terms', json={'value': {'terms': ['urban flooding']}})
    assert terms.json()['next_card'] == 'years'

    years = client.post(f'/api/tasks/{task_id}/answers/years', json={'value': {'choice': 'B', 'from_year': 2021}})
    assert years.json()['state'] == 'searching'
    assert years.json()['job_id']
    duplicate = client.post(f'/api/tasks/{task_id}/answers/years', json={'value': {'choice': 'B', 'from_year': 2021}})
    assert duplicate.json()['job_id'] == years.json()['job_id']
    assert client.queue_calls == [(task_id, 'search')]

    current = client.get(f'/api/tasks/{task_id}')
    assert current.json()['progress']['stage'] == 'search'


def test_mode_answer_caches_real_candidate_options(client, db, monkeypatch):
    publish_base(db)
    create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    client.post(f'/api/tasks/{task_id}/answers/direction', json={'value': {'direction': '城市内涝'}})
    calls = []

    class Candidates:
        def generate(self, direction, mode):
            calls.append((direction, mode))
            return [{
                'value': 'urban flooding',
                'label': '城市内涝（命中 1200，推荐）',
                'description': '降雨与积水问题',
                'preview': 'urban flooding\n适合：领域全景',
            }]

    monkeypatch.setattr('app.main.candidate_service', Candidates())
    first = client.post(f'/api/tasks/{task_id}/answers/mode', json={'value': {'mode': 'A'}})
    second = client.post(f'/api/tasks/{task_id}/answers/mode', json={'value': {'mode': 'A'}})

    assert first.json()['card']['options'][0]['label'] == '城市内涝（命中 1200，推荐）'
    assert second.json()['card']['options'][0]['value'] == 'urban flooding'
    assert calls == [('城市内涝', 'A')]


def test_private_artifact_requires_owner_and_valid_signature(client, db, tmp_path):
    publish_base(db)
    create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    artifact_dir = tmp_path / 'artifacts' / task_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / 'report.docx').write_bytes(b'PK-test')

    listing = client.get(f'/api/tasks/{task_id}/artifacts')
    assert listing.status_code == 200
    artifact = next(item for item in listing.json()['artifacts'] if item['name'] == 'report.docx')
    downloaded = client.get(artifact['url'])
    assert downloaded.status_code == 200
    assert downloaded.content == b'PK-test'

    assert client.get(f'/api/tasks/{task_id}/artifacts/report.docx?signature=bad').status_code in {403, 404}
    assert client.get(f'/api/tasks/{task_id}/artifacts/..%2Fpapers.json').status_code == 404

    other_session = InviteSession(id=str(uuid4()))
    db.add(other_session)
    db.commit()
    other_client = TestClient(app, base_url='https://testserver')
    other_client.post('/api/session', json={})
    assert other_client.get(artifact['url']).status_code == 404


@pytest.mark.parametrize('invalidation', ['expired', 'revoked'])
def test_expired_or_revoked_session_loses_all_private_access_and_owner_is_not_inherited(
    client,
    db,
    tmp_path,
    invalidation,
):
    from datetime import datetime, timedelta, timezone
    from app.security import revoke_session

    publish_base(db)
    session_id = create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    artifact_dir = tmp_path / 'artifacts' / task_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / 'report.docx').write_bytes(b'PK-private')
    listing = client.get(f'/api/tasks/{task_id}/artifacts')
    artifact_url = next(
        item['url'] for item in listing.json()['artifacts'] if item['name'] == 'report.docx'
    )

    if invalidation == 'expired':
        record = db.get(InviteSession, session_id)
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    else:
        revoke_session(db, session_id)

    requests = [
        ('post', '/api/tasks', {'json': {}}),
        (
            'post',
            f'/api/tasks/{task_id}/answers/direction',
            {'json': {'value': {'direction': '不应写入'}}},
        ),
        ('get', '/api/tasks', {}),
        ('get', f'/api/tasks/{task_id}', {}),
        ('get', f'/api/tasks/{task_id}/report', {}),
        ('get', f'/api/tasks/{task_id}/artifacts', {}),
        ('get', artifact_url, {}),
    ]
    for method, url, kwargs in requests:
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 401, (invalidation, method, url, response.text)
        assert response.json() == {'detail': 'Invalid session'}

    db.expire_all()
    assert db.get(Task, task_id).state == 'collecting_mode'

    replacement = client.post('/api/session', json={})
    assert replacement.status_code == 201
    assert replacement.json()['session_id'] != session_id
    assert client.get(f'/api/tasks/{task_id}').status_code == 404
    assert client.get('/api/tasks').json() == {'tasks': []}
    assert client.get(artifact_url).status_code == 404


def test_mobile_artifact_signs_embedded_long_image(client, db, tmp_path):
    from app.artifacts import ArtifactStore

    publish_base(db)
    session_id = create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    artifact_dir = tmp_path / 'artifacts' / task_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / 'mobile.html').write_text(
        '<a href="文献图谱仪表盘.png"><img class="longshot" src="文献图谱仪表盘.png"></a>',
        encoding='utf-8',
    )
    (artifact_dir / '文献图谱仪表盘.png').write_bytes(b'PNG')
    store = ArtifactStore(root=tmp_path / 'artifacts')

    response = client.get(store.signed_url(task_id, 'mobile.html', session_id))

    assert response.status_code == 200
    assert 'src="文献图谱仪表盘.png?signature=' in response.text
    assert 'href="文献图谱仪表盘.png?signature=' in response.text
    image_url = re.search(r'src="([^"]+)"', response.text).group(1)
    image_response = client.get(f'/api/tasks/{task_id}/artifacts/{image_url}')
    assert image_response.status_code == 200
    assert image_response.content == b'PNG'


def test_local_visual_artifacts_are_inline_and_documents_remain_attachments(client, db, tmp_path):
    from app.artifacts import ArtifactStore

    publish_base(db)
    session_id = create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    artifact_dir = tmp_path / 'artifacts' / task_id
    artifact_dir.mkdir(parents=True)
    contents = {
        'desktop.html': b'<html>local</html>',
        'map.svg': b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        'report.docx': b'PK-local-docx',
        'slides.pptx': b'PK-local-pptx',
    }
    for name, content in contents.items():
        (artifact_dir / name).write_bytes(content)

    store = ArtifactStore(root=tmp_path / 'artifacts')
    for name, content in contents.items():
        response = client.get(store.signed_url(task_id, name, session_id))
        expected = 'inline' if name.endswith(('.html', '.svg')) else 'attachment'
        assert response.status_code == 200
        assert response.content == content
        assert response.headers['Content-Disposition'] == f'{expected}; filename="{name}"'
        assert response.headers['Cache-Control'] == 'private, no-store'

    html_url = store.signed_url(task_id, 'desktop.html', session_id)
    assert client.get(f'/api/tasks/{task_id}/artifacts/desktop.html?signature=bad').status_code == 403
    other_client = TestClient(app, base_url='https://testserver')
    other_client.post('/api/session', json={})
    assert other_client.get(html_url).status_code == 404


def test_remote_visual_artifacts_are_inline_and_documents_remain_attachments(client, db, tmp_path, monkeypatch):
    from app.artifacts import ArtifactStore

    publish_base(db)
    session_id = create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    contents = {
        'desktop.html': b'<html>remote</html>',
        'map.svg': b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        'report.docx': b'PK-remote-docx',
        'slides.pptx': b'PK-remote-pptx',
    }

    class RemoteStorage:
        def get_bytes(self, requested_task, filename):
            assert requested_task == task_id
            return contents[filename]

    store = ArtifactStore(root=tmp_path / 'artifacts', remote_client=RemoteStorage())
    monkeypatch.setattr('app.main.ArtifactStore', lambda: store)
    for name, content in contents.items():
        response = client.get(store.signed_url(task_id, name, session_id))
        expected = 'inline' if name.endswith(('.html', '.svg')) else 'attachment'
        assert response.status_code == 200
        assert response.content == content
        assert response.headers['Content-Disposition'] == f'{expected}; filename="{name}"'
        assert response.headers['Cache-Control'] == 'private, no-store'


def test_candidate_model_rate_limit_returns_429_before_paid_call(
    client, db, isolated_rate_limiter, monkeypatch
):
    from app.rate_limit import RateLimitRule

    publish_base(db)
    session_id = create_session(client)
    task_id = client.post('/api/tasks', json={}).json()['id']
    client.post(
        f'/api/tasks/{task_id}/answers/direction',
        json={'value': {'direction': '城市内涝'}},
    )
    isolated_rate_limiter.clock = lambda: 0
    isolated_rate_limiter.rules = {
        'model': {
            'session': RateLimitRule(1, 3600),
            'ip': RateLimitRule(100, 3600),
        },
        'retrieval': {
            'session': RateLimitRule(10, 3600),
            'ip': RateLimitRule(100, 3600),
        },
    }
    assert isolated_rate_limiter.consume(
        'model', session_id=session_id, source_ip='testclient'
    ).allowed

    def unexpected_paid_call(direction, mode):
        raise AssertionError('Candidate model must not be called after quota denial')

    monkeypatch.setattr(
        'app.main.candidate_service',
        type('ForbiddenCandidates', (), {'generate': unexpected_paid_call})(),
    )
    response = client.post(
        f'/api/tasks/{task_id}/answers/mode',
        json={'value': {'mode': 'A'}},
    )

    assert response.status_code == 429
    assert response.headers['Retry-After'] == '3600'
    assert response.json()['detail']['code'] == 'rate_limited'
    assert 'traceback' not in response.text.lower()
    assert '/Users/' not in response.text
