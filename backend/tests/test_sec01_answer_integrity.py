import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Base, InviteSession, Task, TaskAnswer, TaskEvent, TaskJob, TaskProgress
from app.skill_versions import SkillVersionService, load_base_config


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sec01-answer-integrity.db'}",
        connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def harness(session_factory, monkeypatch, tmp_path):
    monkeypatch.setenv('SESSION_SECRET', 'sec01-test-session-secret')
    monkeypatch.setenv('ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    monkeypatch.setenv('REDIS_URL', '')
    get_settings.cache_clear()
    monkeypatch.setattr('app.task_flow.SessionLocal', session_factory)

    queue_calls = []
    lock = threading.Lock()

    class RecordingQueue:
        def enqueue_stage(self, task_id, stage):
            with lock:
                queue_calls.append((task_id, stage))
            with session_factory() as db:
                progress = db.get(TaskProgress, task_id) or TaskProgress(task_id=task_id)
                progress.stage = stage
                progress.message = f'queued:{stage}'
                db.add(progress)
                db.commit()
            return {'id': f'rq-{stage}'}

    monkeypatch.setattr('app.main.queue_adapter', RecordingQueue())
    monkeypatch.setattr(
        'app.main.candidate_service',
        type('EmptyCandidates', (), {'generate': lambda self, direction, mode: []})(),
    )

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, base_url='https://testserver')
    with session_factory() as db:
        service = SkillVersionService(db)
        draft = service.create_draft(None, load_base_config(), actor='sec01-test')
        service.run_regression(draft.id, lambda config: {'passed': True}, actor='sec01-test')
        service.publish(draft.id, actor='sec01-test')
    yield SimpleNamespace(client=client, session_factory=session_factory, queue_calls=queue_calls)
    client.close()
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def create_task(harness):
    session = harness.client.post('/api/session', json={})
    assert session.status_code == 201
    created = harness.client.post('/api/tasks', json={})
    assert created.status_code == 201, created.text
    return created.json()['id']


def answer(harness, task_id, card, value):
    return harness.client.post(f'/api/tasks/{task_id}/answers/{card}', json={'value': value})


def advance_to_years(harness, task_id):
    assert answer(harness, task_id, 'direction', {'direction': '城市内涝'}).status_code == 200
    assert answer(harness, task_id, 'mode', {'mode': 'A'}).status_code == 200
    assert answer(harness, task_id, 'terms', {'terms': ['urban flooding']}).status_code == 200


def snapshot(harness, task_id):
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        return {
            'state': (task.state, task.next_card),
            'answers': db.query(TaskAnswer).filter_by(task_id=task_id).count(),
            'answer_bytes': db.execute(
                text('SELECT COALESCE(SUM(LENGTH(CAST(value AS BLOB))), 0) FROM task_answers WHERE task_id=:id'),
                {'id': task_id},
            ).scalar(),
            'events': db.query(TaskEvent).filter_by(task_id=task_id).count(),
            'event_bytes': db.execute(
                text('SELECT COALESCE(SUM(LENGTH(CAST(payload AS BLOB))), 0) FROM task_events WHERE task_id=:id'),
                {'id': task_id},
            ).scalar(),
            'jobs': db.query(TaskJob).filter_by(task_id=task_id).count(),
            'progress': db.query(TaskProgress).filter_by(task_id=task_id).count(),
        }


def test_repeated_conflicts_are_409_with_zero_new_storage(harness):
    task_id = create_task(harness)
    assert answer(harness, task_id, 'direction', {'direction': '保留第一次方向'}).status_code == 200
    before = snapshot(harness, task_id)

    markers = []
    for index in range(12):
        marker = f'{index}-' + ('X' * 1500)
        markers.append(marker)
        response = answer(harness, task_id, 'direction', {'direction': marker})
        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'answer_conflict'
        assert marker not in response.text

    assert snapshot(harness, task_id) == before
    assert harness.queue_calls == []


def test_years_replay_and_conflict_never_requeue(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    value = {'choice': 'B', 'from_year': 2021}
    first = answer(harness, task_id, 'years', value)
    assert first.status_code == 200
    before = snapshot(harness, task_id)

    for _ in range(5):
        replay = answer(harness, task_id, 'years', value)
        assert replay.status_code == 200
        assert replay.json()['job_id'] == first.json()['job_id']
        assert snapshot(harness, task_id) == before
    assert harness.queue_calls == [(task_id, 'search')]

    conflict = answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2022})
    assert conflict.status_code == 409
    assert snapshot(harness, task_id) == before
    assert harness.queue_calls == [(task_id, 'search')]


def test_non_current_first_answer_is_rejected_without_writes(harness):
    task_id = create_task(harness)
    before = snapshot(harness, task_id)

    response = answer(harness, task_id, 'mode', {'mode': 'A'})

    assert response.status_code == 409
    assert snapshot(harness, task_id) == before
    assert harness.queue_calls == []


def test_body_schema_and_unicode_boundaries_fail_before_write(harness):
    task_id = create_task(harness)
    before = snapshot(harness, task_id)
    oversized = harness.client.post(
        f'/api/tasks/{task_id}/answers/direction',
        content=b'{"value":{"direction":"' + (b'x' * 65_537) + b'"}}',
        headers={'Content-Type': 'application/json'},
    )
    assert oversized.status_code == 413
    unknown = answer(harness, task_id, 'direction', {'direction': 'x', 'unexpected': True})
    assert unknown.status_code == 422
    assert snapshot(harness, task_id) == before

    accepted = answer(harness, task_id, 'direction', {'direction': '城市内涝与地下车库韧性'})
    assert accepted.status_code == 200, accepted.text
    conflict = answer(harness, task_id, 'direction', {'direction': '另一段中文方向'})
    assert conflict.status_code == 409
    assert '另一段中文方向' not in conflict.text
    assert harness.queue_calls == []


def test_delivery_conflict_does_not_requeue(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    assert answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2021}).status_code == 200
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'dashboard_ready'
        task.next_card = 'adjustment'
        db.commit()
    assert answer(harness, task_id, 'adjustment', {'adjustment': 'continue'}).status_code == 200
    first = answer(harness, task_id, 'delivery', {'form': 'C'})
    assert first.status_code == 200
    before = snapshot(harness, task_id)

    conflict = answer(harness, task_id, 'delivery', {'form': 'A'})

    assert conflict.status_code == 409
    assert snapshot(harness, task_id) == before
    assert harness.queue_calls == [(task_id, 'search'), (task_id, 'generate')]


def test_terms_revision_after_adjustment_remains_legal_and_replay_is_zero_write(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    assert answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2021}).status_code == 200
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'dashboard_ready'
        task.next_card = 'adjustment'
        db.commit()
    assert answer(harness, task_id, 'adjustment', {'adjustment': ['terms']}).status_code == 200
    revised = answer(harness, task_id, 'terms', {'terms': ['urban resilience', 'drainage']})
    assert revised.status_code == 200
    before = snapshot(harness, task_id)

    replay = answer(harness, task_id, 'terms', {'terms': ['urban resilience', 'drainage']})

    assert replay.status_code == 200
    assert snapshot(harness, task_id) == before
    assert harness.queue_calls == [(task_id, 'search'), (task_id, 'search')]


def test_same_value_new_adjustment_cycle_is_allowed(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    assert answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2021}).status_code == 200
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'dashboard_ready'
        task.next_card = 'adjustment'
        db.commit()
    value = {'adjustment': ['terms']}
    assert answer(harness, task_id, 'adjustment', value).status_code == 200
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'dashboard_ready'
        task.next_card = 'adjustment'
        db.commit()

    new_cycle = answer(harness, task_id, 'adjustment', value)

    assert new_cycle.status_code == 200
    assert new_cycle.json()['next_card'] == 'terms'
    revised = answer(harness, task_id, 'terms', {'terms': ['urban flooding']})
    assert revised.status_code == 200
    assert revised.json()['state'] == 'searching'


def test_malformed_json_and_duplicate_keys_fail_before_write(harness):
    task_id = create_task(harness)
    before = snapshot(harness, task_id)
    for body in (
        b'{"value":{"direction":"first","direction":"second"}}',
        b'{"value":{"direction":NaN}}',
        b'{"value":{"direction":{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":1}}}}}}}}}}',
    ):
        response = harness.client.post(
            f'/api/tasks/{task_id}/answers/direction',
            content=body,
            headers={'Content-Type': 'application/json'},
        )
        assert response.status_code == 422, response.text
    assert snapshot(harness, task_id) == before


def test_concurrent_distinct_answers_have_exactly_one_winner(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    before = snapshot(harness, task_id)
    barrier = threading.Barrier(8)
    outcomes = []

    def submit(index):
        barrier.wait()
        response = answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2020 + index})
        outcomes.append((response.status_code, response.text))

    threads = [threading.Thread(target=submit, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads)
    statuses = [status for status, _ in outcomes]
    assert statuses.count(200) == 1, outcomes
    assert statuses.count(409) == 7, outcomes
    assert snapshot(harness, task_id)['answers'] == before['answers'] + 1
    assert snapshot(harness, task_id)['jobs'] == 1
    assert harness.queue_calls == [(task_id, 'search')]


def test_concurrent_identical_answers_return_same_result_once(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)
    before = snapshot(harness, task_id)
    barrier = threading.Barrier(8)
    outcomes = []

    def submit():
        barrier.wait()
        response = answer(harness, task_id, 'years', {'choice': 'B', 'from_year': 2021})
        outcomes.append((response.status_code, response.json()))

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads)
    assert [status for status, _ in outcomes] == [200] * 8, outcomes
    assert len({payload['job_id'] for _, payload in outcomes}) == 1
    assert snapshot(harness, task_id)['answers'] == before['answers'] + 1
    assert snapshot(harness, task_id)['jobs'] == 1
    assert snapshot(harness, task_id)['events'] == before['events']
    assert harness.queue_calls == [(task_id, 'search')]


def test_frontend_year_and_delivery_shorthand_are_accepted(harness):
    task_id = create_task(harness)
    advance_to_years(harness, task_id)

    years = answer(harness, task_id, 'years', {'years': 'C'})
    assert years.status_code == 200, years.text
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        task.state = 'dashboard_ready'
        task.next_card = 'adjustment'
        db.commit()
    assert answer(harness, task_id, 'adjustment', {'adjustment': 'continue'}).status_code == 200
    delivered = answer(harness, task_id, 'delivery', {'delivery': 'A'})
    assert delivered.status_code == 200, delivered.text
