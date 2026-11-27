from datetime import datetime, timezone
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
from app.models import InviteSession, Task, TaskAnswer, TaskEvent, TaskProgress
from app.snapshots import snapshot_token


@pytest.fixture(autouse=True)
def configure_snapshot_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('SESSION_SECRET', 'snapshot-test-session-secret')
    monkeypatch.setenv('ADMIN_TOKEN', 'snapshot-test-admin-token')
    monkeypatch.setenv('WORKER_SHARED_SECRET', 'snapshot-test-worker-secret')
    monkeypatch.setenv('ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    monkeypatch.delenv('TASK_STORE_AUTHORITY', raising=False)
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


def create_session():
    response = TestClient(app, base_url='https://testserver').post('/api/session', json={})
    assert response.status_code == 201
    return SimpleNamespace(
        id=response.json()['session_id'],
        headers={'Cookie': response.headers['set-cookie'].split(';', 1)[0]},
    )


def seed_completed_task(database, tmp_path):
    owner = create_session()
    task_id = str(uuid4())
    created_at = datetime(2026, 11, 27, 10, 40, tzinfo=timezone.utc)
    with database.session_factory() as db:
        db.add(Task(id=task_id, session_id=owner.id, state='done', created_at=created_at, updated_at=created_at))
        answers = [
            ('direction', {'direction': '自动驾驶测试'}),
            ('mode', {'mode': 'A'}),
            ('terms', {'terms': ['仿真测试', '公共道路测试']}),
            ('years', {'years': 'A'}),
            ('adjustment', {'adjustment': ['continue']}),
            ('delivery', {'delivery': 'A'}),
        ]
        for card_id, value in answers:
            db.add(TaskAnswer(task_id=task_id, card_id=card_id, value=value, result_state='done'))
        db.add(TaskEvent(task_id=task_id, event_type='terms_candidates', payload={
            'direction': '自动驾驶测试',
            'mode': 'A',
            'options': [
                {'value': '仿真测试', 'label': '仿真测试（命中 248）', 'description': '虚拟环境测试', 'preview': 'simulation testing'},
                {'value': '公共道路测试', 'label': '公共道路测试（命中 476）', 'description': '真实道路测试', 'preview': 'public road testing'},
            ],
        }))
        db.add(TaskProgress(
            task_id=task_id,
            stage='generate',
            message='交付文件已生成',
            percent=100,
            checkpoint={'stage': 'generate', 'clean': True, 'limited_count': 28, 'unlimited_count': 24},
        ))
        db.commit()

    directory = tmp_path / 'artifacts' / task_id
    directory.mkdir(parents=True)
    (directory / 'desktop.html').write_text('<html><body>snapshot dashboard</body></html>', encoding='utf-8')
    (directory / 'mobile.html').write_text('<html><body>snapshot mobile</body></html>', encoding='utf-8')
    (directory / 'outline.md').write_text('# 提纲\n\n- 领域格局', encoding='utf-8')
    (directory / 'sample.md').write_text('# 样章\n\n方向卡内容', encoding='utf-8')
    (directory / '综述初稿.md').write_text('# 正文\n\n自动驾驶测试综述 [1]。\n\n## 参考文献\n\n[1] 真实文献', encoding='utf-8')
    (directory / '综述初稿.docx').write_bytes(b'docx snapshot')
    return owner, task_id


def seed_failed_b_task(database):
    owner = create_session()
    task_id = str(uuid4())
    created_at = datetime(2026, 11, 27, 11, 17, tzinfo=timezone.utc)
    with database.session_factory() as db:
        db.add(Task(id=task_id, session_id=owner.id, state='error', created_at=created_at, updated_at=created_at))
        for card_id, value in (
            ('direction', {'direction': '城市内涝与地下车库韧性'}),
            ('mode', {'mode': 'B'}),
            ('delivery', {'delivery': 'A'}),
        ):
            db.add(TaskAnswer(task_id=task_id, card_id=card_id, value=value, result_state='error'))
        db.add(TaskProgress(
            task_id=task_id,
            stage='generate',
            message='任务执行失败，请稍后重试。',
            percent=55,
            traceback='protected failure',
        ))
        db.commit()
        task = db.get(Task, task_id)
        token = snapshot_token(task)
    return owner, task_id, token


def test_failed_b_generate_can_resume_once_with_capability(client, database, monkeypatch):
    _, task_id, token = seed_failed_b_task(database)
    calls = []
    monkeypatch.setattr(
        'app.main.queue_adapter.enqueue_stage',
        lambda task_id, stage, session_id=None: calls.append((task_id, stage, session_id)),
    )

    response = client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    )

    assert response.status_code == 200
    assert response.json()['report_url'] == f'/tasks/{task_id}/report'
    assert calls and calls[0][0:2] == (task_id, 'recover_generate')
    assert client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    ).status_code == 409

    with database.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'error'
        db.add(TaskEvent(
            task_id=task_id,
            event_type='failed',
            payload={'stage': 'generate', 'message': 'missing artifacts'},
        ))
        db.commit()
    retry = client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    )
    assert retry.status_code == 200
    assert len(calls) == 2


def test_resume_uses_existing_artifacts_when_web_pool_is_present(client, database, tmp_path, monkeypatch):
    _, task_id, token = seed_failed_b_task(database)
    directory = tmp_path / 'artifacts' / task_id
    directory.mkdir(parents=True)
    (directory / 'papers.json').write_text('{"papers": []}', encoding='utf-8')
    calls = []
    monkeypatch.setattr(
        'app.main.queue_adapter.enqueue_stage',
        lambda task_id, stage, session_id=None: calls.append(stage),
    )

    response = client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    )

    assert response.status_code == 200
    assert calls == ['generate']


def test_resume_generate_rejects_invalid_capability_and_non_failed_task(client, database, monkeypatch):
    _, task_id, token = seed_failed_b_task(database)
    monkeypatch.setattr('app.main.queue_adapter.enqueue_stage', lambda *args, **kwargs: None)

    assert client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': 'invalid'},
    ).status_code == 404

    with database.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'done'
        db.commit()
    assert client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    ).status_code == 409


def test_internal_artifact_recovery_requires_worker_token(client, database, tmp_path):
    _, task_id = seed_completed_task(database, tmp_path)
    worker_headers = {'X-Worker-Token': 'snapshot-test-worker-secret'}

    assert client.get(f'/api/internal/artifacts/{task_id}').status_code == 403
    listing = client.get(f'/api/internal/artifacts/{task_id}', headers=worker_headers)
    assert listing.status_code == 200
    assert 'papers.json' not in listing.json()['artifacts']
    assert 'desktop.html' in listing.json()['artifacts']

    download = client.get(
        f'/api/internal/artifacts/{task_id}/desktop.html',
        headers=worker_headers,
    )
    assert download.status_code == 200
    assert download.text == '<html><body>snapshot dashboard</body></html>'
    assert client.get(
        f'/api/internal/artifacts/{task_id}/..%2Fsecret',
        headers=worker_headers,
    ).status_code == 404


def test_owner_can_mint_read_only_snapshot_link(client, database, tmp_path):
    owner, task_id = seed_completed_task(database, tmp_path)

    response = client.post(f'/api/tasks/{task_id}/snapshots', json={}, headers=owner.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload['task_id'] == task_id
    assert payload['direction'] == '自动驾驶测试'
    assert payload['mode'] == 'A'
    assert payload['token']
    assert payload['index_url'].endswith(f"/snapshots/{task_id}/{payload['token']}")
    assert [stage['id'] for stage in payload['stages']] == [
        'direction', 'mode', 'terms', 'years', 'search', 'dashboard', 'adjustment', 'delivery', 'report',
    ]
    assert 'session_id' not in payload


def test_snapshot_metadata_is_public_only_with_valid_capability(client, database, tmp_path):
    owner, task_id = seed_completed_task(database, tmp_path)
    minted = client.post(f'/api/tasks/{task_id}/snapshots', json={}, headers=owner.headers).json()
    token = minted['token']

    response = client.get(f'/api/snapshots/{task_id}/{token}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['answers']['terms']['terms'] == ['仿真测试', '公共道路测试']
    assert payload['cards']['terms']['options'][0]['label'] == '仿真测试（命中 248）'
    assert payload['report']['body'].startswith('# 正文')
    assert payload['dashboard']['desktop_url'].endswith('/artifacts/desktop.html')
    assert payload['progress']['percent'] == 100
    assert client.get(f'/api/snapshots/{task_id}/invalid-token').status_code == 404


def test_snapshot_artifacts_are_read_only_and_sandboxed(client, database, tmp_path):
    owner, task_id = seed_completed_task(database, tmp_path)
    minted = client.post(f'/api/tasks/{task_id}/snapshots', json={}, headers=owner.headers).json()
    token = minted['token']

    dashboard = client.get(f'/api/snapshots/{task_id}/{token}/artifacts/desktop.html')
    report = client.get(f'/api/snapshots/{task_id}/{token}/artifacts/综述初稿.docx')

    assert dashboard.status_code == 200
    assert dashboard.text == '<html><body>snapshot dashboard</body></html>'
    assert 'sandbox' in dashboard.headers['content-security-policy']
    assert report.status_code == 200
    assert report.content == b'docx snapshot'
    assert report.headers['content-disposition'].startswith('attachment')
    assert client.get(f'/api/snapshots/{task_id}/{token}/artifacts/..%2Fsecret').status_code == 404
    assert client.post(f'/api/snapshots/{task_id}/{token}/artifacts/desktop.html', content='changed').status_code == 405


def test_failed_d_generate_can_resume_with_capability(client, database, monkeypatch):
    _, task_id, token = seed_failed_b_task(database)
    with database.session_factory() as db:
        answer = db.query(TaskAnswer).filter_by(task_id=task_id, card_id='mode').one()
        answer.value = {'mode': 'D'}
        db.commit()
    calls = []
    monkeypatch.setattr(
        'app.main.queue_adapter.enqueue_stage',
        lambda task_id, stage, session_id=None: calls.append(stage),
    )

    response = client.post(
        f'/api/tasks/{task_id}/resume-generate',
        headers={'X-Snapshot-Token': token},
    )

    assert response.status_code == 200
    assert calls == ['recover_generate']
