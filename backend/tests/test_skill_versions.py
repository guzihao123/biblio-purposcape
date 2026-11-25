import json
from threading import Barrier, Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import initialize_database
from app.models import Base, InviteSession, SkillVersion, SkillVersionEvent, Task
from app.skill_versions import SkillVersionError, SkillVersionService, load_base_config


BASE_CONFIG = {
    'cards': {
        'order': ['direction', 'mode', 'terms', 'years', 'adjustment', 'delivery'],
        'mode': {'title': '这次洞察的用途'},
        'terms': {'multiple': True},
        'adjustment': {'continue_veto': True},
        'delivery': {'last_confirmation': True},
    },
    'modes': {'A': {'word_range': [1500, 2500]}},
    'visual': {'theme': 'full-power'},
}


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
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def service(db):
    return SkillVersionService(db)


@pytest.fixture
def file_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'skill-version-concurrency.db'}",
        connect_args={'check_same_thread': False, 'timeout': 10},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def run_service_calls_concurrently(factory, calls):
    barrier = Barrier(len(calls))
    outcomes = [None] * len(calls)

    def invoke(index, method_name, args):
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                service = SkillVersionService(session)
                outcomes[index] = getattr(service, method_name)(*args)
            except BaseException as error:
                outcomes[index] = error

    threads = [
        Thread(target=invoke, args=(index, method_name, args))
        for index, (method_name, args) in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    return outcomes


def passing_regression(config):
    return {'passed': True, 'checks': {'hcc': '9/9', 'frontend': 'passed'}}


def failing_regression(config):
    return {'passed': False, 'errors': ['HCC evidence regression failed']}


def publish_base(service):
    draft = service.create_draft(None, BASE_CONFIG, actor='admin-test')
    service.run_regression(draft.id, passing_regression, actor='admin-test')
    return service.publish(draft.id, actor='admin-test')


def test_publish_requires_a_passing_regression(service):
    draft = service.create_draft(None, BASE_CONFIG, actor='admin-test')
    service.run_regression(draft.id, failing_regression, actor='admin-test')

    with pytest.raises(SkillVersionError, match='regression'):
        service.publish(draft.id, actor='admin-test')

    assert service.active_version() is None
    assert draft.state == 'draft'


def test_regression_result_is_persisted_before_publish(service):
    draft = service.create_draft(None, BASE_CONFIG, actor='admin-test')
    report = service.run_regression(draft.id, passing_regression, actor='admin-test')

    assert report['passed'] is True
    persisted = service.db.get(SkillVersion, draft.id)
    assert persisted.regression_report['checks']['hcc'] == '9/9'
    published = service.publish(draft.id, actor='admin-test')
    assert published.state == 'published'
    assert service.active_version().id == published.id


def test_completed_task_keeps_pinned_version_after_publication_and_rollback(service, db):
    old = publish_base(service)
    db.add(InviteSession(id='owner'))
    task = Task(id='completed-task', session_id='owner', skill_version_id=old.id, state='done')
    db.add(task)
    db.commit()

    changed = json.loads(json.dumps(BASE_CONFIG))
    changed['cards']['mode']['title'] = '新文案'
    new = service.create_draft(old.id, changed, actor='admin-test')
    service.run_regression(new.id, passing_regression, actor='admin-test')
    service.publish(new.id, actor='admin-test')

    assert service.get_task_version(task).id == old.id
    assert service.get_task_version(task).content['cards']['mode']['title'] == '这次洞察的用途'

    service.rollback(old.id, actor='admin-test')
    assert service.active_version().id == old.id
    assert service.get_task_version(task).id == old.id


def test_new_task_is_pinned_to_current_published_version(service, db):
    first = publish_base(service)
    db.add(InviteSession(id='owner'))
    db.commit()
    task = service.create_task(session_id='owner')
    assert task.skill_version_id == first.id
    task.state = 'done'
    db.add(task)
    db.commit()

    second = service.create_draft(first.id, BASE_CONFIG, actor='admin-test')
    service.run_regression(second.id, passing_regression, actor='admin-test')
    service.publish(second.id, actor='admin-test')
    assert service.get_task_version(task).id == first.id


def test_active_task_blocks_publish_and_rollback_until_it_finishes(service, db):
    first = publish_base(service)
    db.add(InviteSession(id='owner'))
    task = Task(id='active-task', session_id='owner', skill_version_id=first.id, state='generating')
    db.add(task)
    db.commit()
    second = service.create_draft(first.id, BASE_CONFIG, actor='admin-test')
    service.run_regression(second.id, passing_regression, actor='admin-test')

    with pytest.raises(SkillVersionError, match='active tasks'):
        service.publish(second.id, actor='admin-test')
    assert service.active_version().id == first.id
    assert second.state == 'draft'

    task.state = 'done'
    db.add(task)
    db.commit()
    service.publish(second.id, actor='admin-test')
    db.add(Task(id='rollback-task', session_id='owner', skill_version_id=second.id, state='searching'))
    db.commit()
    with pytest.raises(SkillVersionError, match='active tasks'):
        service.rollback(first.id, actor='admin-test')

    rollback_task = db.get(Task, 'rollback-task')
    rollback_task.state = 'done'
    db.add(rollback_task)
    db.commit()
    service.rollback(first.id, actor='admin-test')
    assert service.get_task_version(task).id == first.id


def test_draft_deep_copies_parent_and_published_content_is_immutable(service):
    parent = publish_base(service)
    draft = service.create_draft(parent.id, BASE_CONFIG, actor='admin-test')
    draft.content['cards']['mode']['title'] = '草稿修改'

    assert parent.content['cards']['mode']['title'] == '这次洞察的用途'
    with pytest.raises(SkillVersionError, match='immutable'):
        service.replace_content(parent.id, BASE_CONFIG, actor='admin-test')


def test_locked_confirmation_order_and_invariants_cannot_be_edited(service):
    invalid = json.loads(json.dumps(BASE_CONFIG))
    invalid['cards']['order'] = ['mode', 'direction', 'terms', 'years', 'adjustment', 'delivery']
    with pytest.raises(SkillVersionError, match='confirmation order'):
        service.create_draft(None, invalid, actor='admin-test')

    invalid = json.loads(json.dumps(BASE_CONFIG))
    invalid['cards']['terms']['multiple'] = False
    with pytest.raises(SkillVersionError, match='terms'):
        service.create_draft(None, invalid, actor='admin-test')

    invalid = json.loads(json.dumps(BASE_CONFIG))
    invalid['cards']['delivery']['last_confirmation'] = False
    with pytest.raises(SkillVersionError, match='delivery'):
        service.create_draft(None, invalid, actor='admin-test')


def test_publish_and_rollback_record_actor_diff_and_regression(service):
    first = publish_base(service)
    changed = json.loads(json.dumps(BASE_CONFIG))
    changed['visual']['theme'] = 'full-power-v2'
    second = service.create_draft(first.id, changed, actor='admin-editor')
    service.run_regression(second.id, passing_regression, actor='admin-editor')
    service.publish(second.id, actor='admin-editor')
    service.rollback(first.id, actor='admin-rollback')

    events = service.history()
    assert any(event.actor == 'admin-editor' and event.event_type == 'published' for event in events)
    rollback = [event for event in events if event.event_type == 'rolled_back'][-1]
    assert rollback.actor == 'admin-rollback'
    assert rollback.diff['active_version']['from'] == second.id
    assert rollback.diff['active_version']['to'] == first.id
    assert rollback.regression_report['passed'] is True


def test_only_one_version_is_published_after_replacement(service):
    first = publish_base(service)
    second = service.create_draft(first.id, BASE_CONFIG, actor='admin-test')
    service.run_regression(second.id, passing_regression, actor='admin-test')
    service.publish(second.id, actor='admin-test')

    assert service.db.get(SkillVersion, first.id).state == 'archived'
    assert service.db.get(SkillVersion, second.id).state == 'published'
    assert service.db.query(SkillVersion).filter_by(state='published').count() == 1


def test_legacy_database_gains_nullable_task_version_without_losing_task(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-versions.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE invite_sessions (id VARCHAR(36) PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL)'))
            connection.execute(text("INSERT INTO invite_sessions (id) VALUES ('legacy-owner')"))
            connection.execute(text("INSERT INTO tasks (id, session_id) VALUES ('legacy-task', 'legacy-owner')"))

        initialize_database(engine)
        factory = sessionmaker(bind=engine)
        with factory() as session:
            task = session.get(Task, 'legacy-task')
            assert task.session_id == 'legacy-owner'
            assert task.skill_version_id is None
    finally:
        engine.dispose()


def test_bundled_base_version_loads_and_passes_locked_invariants(service):
    config = load_base_config()

    assert config['cards']['order'] == [
        'direction', 'mode', 'terms', 'years', 'adjustment', 'delivery'
    ]
    assert config['visual']['theme'] == 'full-power'
    draft = service.create_draft(None, config, actor='admin-test')
    assert draft.state == 'draft'


def test_admin_draft_route_rejects_missing_token_and_accepts_separate_admin_token(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import get_db
    from app.main import app

    monkeypatch.setenv('ADMIN_TOKEN', 'test-admin-token')
    get_settings.cache_clear()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, base_url='https://testserver')
        payload = {'parent_id': None, 'content': BASE_CONFIG}
        rejected = client.post('/api/admin/skill/drafts', json=payload)
        assert rejected.status_code == 403

        accepted = client.post(
            '/api/admin/skill/drafts',
            json=payload,
            headers={'X-Admin-Token': 'test-admin-token'},
        )
        assert accepted.status_code == 201
        assert accepted.json()['state'] == 'draft'

        monkeypatch.setattr('app.main.skill_regression_runner', passing_regression)
        version_id = accepted.json()['id']
        regression = client.post(
            f'/api/admin/skill/versions/{version_id}/regression',
            headers={'X-Admin-Token': 'test-admin-token'},
        )
        assert regression.status_code == 200
        assert regression.json()['passed'] is True
        published = client.post(
            f'/api/admin/skill/versions/{version_id}/publish',
            headers={'X-Admin-Token': 'test-admin-token'},
        )
        assert published.status_code == 200
        assert published.json()['state'] == 'published'
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()


def test_concurrent_sibling_publish_has_one_winner_and_one_current_version(file_session_factory):
    with file_session_factory() as session:
        service = SkillVersionService(session)
        base = publish_base(service)
        drafts = [service.create_draft(base.id, BASE_CONFIG) for _ in range(2)]
        for draft in drafts:
            service.run_regression(draft.id, passing_regression)
        draft_ids = [draft.id for draft in drafts]

    outcomes = run_service_calls_concurrently(
        file_session_factory,
        [('publish', (version_id,)) for version_id in draft_ids],
    )

    winners = [result for result in outcomes if isinstance(result, SkillVersion)]
    conflicts = [result for result in outcomes if isinstance(result, SkillVersionError)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert 'parent' in str(conflicts[0])
    assert all(isinstance(result, (SkillVersion, SkillVersionError)) for result in outcomes)

    with file_session_factory() as session:
        published = session.query(SkillVersion).filter_by(state='published').all()
        assert len(published) == 1
        assert published[0].id == winners[0].id
        loser_id = next(version_id for version_id in draft_ids if version_id != winners[0].id)
        assert session.get(SkillVersion, loser_id).state == 'draft'
        publish_events = session.query(SkillVersionEvent).filter(
            SkillVersionEvent.version_id.in_(draft_ids),
            SkillVersionEvent.event_type == 'published',
        ).all()
        assert len(publish_events) == 1


def test_concurrent_duplicate_transitions_drain_tasks_and_are_idempotent(file_session_factory):
    with file_session_factory() as session:
        service = SkillVersionService(session)
        base = publish_base(service)
        original_content = json.loads(json.dumps(base.content))
        session.add(InviteSession(id='owner'))
        old_task = Task(
            id='old-task', session_id='owner', skill_version_id=base.id, state='generating'
        )
        session.add(old_task)
        session.commit()
        second = service.create_draft(base.id, BASE_CONFIG)
        service.run_regression(second.id, passing_regression)
        base_id, second_id = base.id, second.id

    calls = [('publish', (second_id,)), ('publish', (second_id,))]
    blocked = run_service_calls_concurrently(file_session_factory, calls)
    assert all(isinstance(result, SkillVersionError) for result in blocked)
    assert all('active tasks' in str(result) for result in blocked)

    with file_session_factory() as session:
        task = session.get(Task, 'old-task')
        task.state = 'done'
        session.commit()

    published = run_service_calls_concurrently(file_session_factory, calls)
    assert [result.id for result in published] == [second_id, second_id]

    with file_session_factory() as session:
        session.add(Task(
            id='rollback-task', session_id='owner', skill_version_id=second_id, state='verifying'
        ))
        session.commit()

    rollback_calls = [('rollback', (base_id,)), ('rollback', (base_id,))]
    blocked = run_service_calls_concurrently(file_session_factory, rollback_calls)
    assert all(isinstance(result, SkillVersionError) for result in blocked)
    assert all('active tasks' in str(result) for result in blocked)

    with file_session_factory() as session:
        task = session.get(Task, 'rollback-task')
        task.state = 'done'
        session.commit()

    rolled_back = run_service_calls_concurrently(file_session_factory, rollback_calls)
    assert [result.id for result in rolled_back] == [base_id, base_id]

    with file_session_factory() as session:
        assert session.query(SkillVersion).filter_by(state='published').one().id == base_id
        assert session.query(SkillVersionEvent).filter_by(
            version_id=second_id, event_type='published'
        ).count() == 1
        assert session.query(SkillVersionEvent).filter_by(
            version_id=base_id, event_type='rolled_back'
        ).count() == 1
        pinned_task = session.get(Task, 'old-task')
        assert pinned_task.skill_version_id == base_id
        assert session.get(SkillVersion, base_id).content == original_content


def test_concurrent_drafts_receive_distinct_version_numbers(file_session_factory):
    with file_session_factory() as session:
        base = publish_base(SkillVersionService(session))
        parent_id = base.id

    outcomes = run_service_calls_concurrently(
        file_session_factory,
        [('create_draft', (parent_id, BASE_CONFIG)) for _ in range(2)],
    )

    assert all(isinstance(result, SkillVersion) for result in outcomes)
    assert len({result.version for result in outcomes}) == 2


def test_later_drafts_cannot_mutate_published_fields_or_original_audit(service):
    published = publish_base(service)
    original = {
        'content': json.loads(json.dumps(published.content)),
        'content_hash': published.content_hash,
        'parent_id': published.parent_id,
    }
    original_events = [
        (event.id, event.version_id, event.event_type, json.loads(json.dumps(event.diff)))
        for event in service.history()
    ]

    changed = json.loads(json.dumps(BASE_CONFIG))
    changed['cards']['mode']['title'] = '后续草稿'
    draft = service.create_draft(published.id, changed)
    changed['visual']['theme'] = 'changed-again'
    service.replace_content(draft.id, changed)
    service.run_regression(draft.id, failing_regression)
    with pytest.raises(SkillVersionError, match='regression'):
        service.publish(draft.id)
    with pytest.raises(SkillVersionError, match='immutable'):
        service.replace_content(published.id, changed)
    with pytest.raises(SkillVersionError, match='requires a draft'):
        service.run_regression(published.id, passing_regression)

    persisted = service.db.get(SkillVersion, published.id)
    assert persisted.content == original['content']
    assert persisted.content_hash == original['content_hash']
    assert persisted.parent_id == original['parent_id']
    current_events = [
        (event.id, event.version_id, event.event_type, event.diff)
        for event in service.history()
    ]
    assert current_events[:len(original_events)] == original_events


def test_regression_and_content_replacement_have_one_commit_order(file_session_factory):
    with file_session_factory() as session:
        service = SkillVersionService(session)
        base = publish_base(service)
        draft = service.create_draft(base.id, BASE_CONFIG)
        draft_id = draft.id

    runner_started = Event()
    finish_runner = Event()
    replacement_attempted = Event()
    outcomes = [None, None]

    def blocking_regression(content):
        runner_started.set()
        assert finish_runner.wait(timeout=10)
        return passing_regression(content)

    def regress():
        with file_session_factory() as session:
            try:
                SkillVersionService(session).run_regression(draft_id, blocking_regression)
            except BaseException as error:
                outcomes[0] = error

    def replace():
        with file_session_factory() as session:
            try:
                changed = json.loads(json.dumps(BASE_CONFIG))
                changed['cards']['mode']['title'] = '回归期间的新内容'
                replacement_attempted.set()
                SkillVersionService(session).replace_content(draft_id, changed)
            except BaseException as error:
                outcomes[1] = error

    regression_thread = Thread(target=regress)
    replacement_thread = Thread(target=replace)
    regression_thread.start()
    assert runner_started.wait(timeout=10)
    replacement_thread.start()
    assert replacement_attempted.wait(timeout=10)
    finish_runner.set()
    regression_thread.join(timeout=20)
    replacement_thread.join(timeout=20)

    assert not regression_thread.is_alive()
    assert not replacement_thread.is_alive()
    assert outcomes == [None, None]
    with file_session_factory() as session:
        draft = session.get(SkillVersion, draft_id)
        assert draft.content['cards']['mode']['title'] == '回归期间的新内容'
        assert draft.regression_report is None
        with pytest.raises(SkillVersionError, match='regression'):
            SkillVersionService(session).publish(draft_id)


def test_api_style_task_pinning_and_publish_cannot_cross_the_drain_gap(file_session_factory):
    with file_session_factory() as session:
        service = SkillVersionService(session)
        base = publish_base(service)
        session.add(InviteSession(id='owner'))
        session.commit()
        second = service.create_draft(base.id, BASE_CONFIG)
        service.run_regression(second.id, passing_regression)
        base_id, second_id = base.id, second.id

    version_read = Event()
    allow_task_insert = Event()
    publish_attempted = Event()
    publish_finished = Event()
    outcomes = [None, None]

    def create_task_like_api():
        with file_session_factory() as session:
            try:
                # The route performs its idempotency read before active_version(),
                # then inserts and commits Task directly in the same session.
                session.query(Task).filter_by(id='idempotency-miss').one_or_none()
                active = SkillVersionService(session).active_version()
                task = Task(
                    id='racing-task',
                    session_id='owner',
                    skill_version_id=active.id,
                    state='collecting_mode',
                )
                version_read.set()
                assert allow_task_insert.wait(timeout=10)
                session.add(task)
                session.commit()
                outcomes[0] = task.skill_version_id
            except BaseException as error:
                outcomes[0] = error

    def publish():
        with file_session_factory() as session:
            try:
                assert version_read.wait(timeout=10)
                publish_attempted.set()
                outcomes[1] = SkillVersionService(session).publish(second_id)
            except BaseException as error:
                outcomes[1] = error
            finally:
                publish_finished.set()

    task_thread = Thread(target=create_task_like_api)
    publish_thread = Thread(target=publish)
    task_thread.start()
    assert version_read.wait(timeout=10)
    publish_thread.start()
    assert publish_attempted.wait(timeout=10)
    try:
        assert not publish_finished.wait(timeout=0.2)
    finally:
        allow_task_insert.set()
    task_thread.join(timeout=20)
    publish_thread.join(timeout=20)

    assert not task_thread.is_alive()
    assert not publish_thread.is_alive()
    assert outcomes[0] == base_id
    assert isinstance(outcomes[1], SkillVersionError)
    assert 'active tasks' in str(outcomes[1])
    with file_session_factory() as session:
        assert session.get(Task, 'racing-task').skill_version_id == base_id
        assert session.query(SkillVersion).filter_by(state='published').one().id == base_id
