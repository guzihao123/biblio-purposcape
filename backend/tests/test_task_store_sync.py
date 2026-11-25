from copy import deepcopy
import traceback

import pytest

from app.task_store_sync import (
    TaskStoreRevisionConflict,
    TaskStoreSync,
    TaskStoreSyncError,
)


SENSITIVE_MESSAGE = (
    'token=super-secret-token; SQL=SELECT * FROM private_tasks; '
    'provider={"body":"private-provider-response"}; '
    'path=/Users/alice/private/task.db'
)
SENSITIVE_FRAGMENTS = (
    'super-secret-token',
    'SELECT * FROM private_tasks',
    'private-provider-response',
    '/Users/alice/private/task.db',
)
SKILL_VERSION = {
    'id': 'skill-v1',
    'version': 1,
    'parent_id': None,
    'state': 'published',
    'content': {'cards': {'direction': {}}},
    'content_hash': 'a' * 64,
    'regression_report': {'passed': True},
    'created_at': '2026-11-24T00:00:00Z',
    'published_at': '2026-11-24T00:00:00Z',
}
QUOTA = {'limit': 2, 'window_seconds': 86400}


class FakeProviderError(RuntimeError):
    def __init__(self, code, message=SENSITIVE_MESSAGE):
        self.code = code
        super().__init__(message)


class FakePrimaryStoreClient:
    """In-memory contract fake; it never performs network or database I/O."""

    def __init__(self):
        self.sessions = {}
        self.skill_versions = {}
        self.tasks = {}
        self.task_keys = {}
        self.artifacts = {}
        self.quota_charges = {}
        self.failures = {}
        self.events = []
        self.state_write_attempts = 0
        self.expected_revisions = []
        self.before_state_write = None
        self.before_answer = None
        self.answer_attempts = 0

    def _maybe_fail(self, operation):
        error = self.failures.get(operation)
        if error is not None:
            raise error

    def _owned_task(self, task_id, session_id):
        task = self.tasks.get(task_id)
        if task is None or task['session_id'] != session_id:
            raise FakeProviderError('task_not_found')
        return task

    @staticmethod
    def _task_result(task, replayed):
        result = deepcopy(task)
        result['replayed'] = replayed
        return result

    def create_anonymous_session(self, client_ip='', user_agent='', session_id=None):
        self.events.append('sync_session')
        self._maybe_fail('sync_session')
        assert session_id is not None
        self.sessions[session_id] = {
            'id': session_id,
            'client_ip': client_ip,
            'user_agent': user_agent,
        }
        return session_id

    def sync_skill_version(self, version):
        self.events.append('sync_skill_version')
        self._maybe_fail('sync_skill_version')
        saved = deepcopy(version)
        self.skill_versions[saved['id']] = saved
        return deepcopy(saved)

    def create_task(
        self,
        session_id,
        idempotency_key,
        skill_version_id,
        quota,
        state='collecting_mode',
        next_card='direction',
        task_id=None,
    ):
        self.events.append('create_task')
        self._maybe_fail('create_task')
        key = idempotency_key.strip()
        index = (session_id, key)
        existing_id = self.task_keys.get(index)
        if existing_id is not None:
            return self._task_result(self.tasks[existing_id], replayed=True)
        if session_id not in self.sessions:
            raise FakeProviderError('session_not_found')
        skill = self.skill_versions.get(skill_version_id)
        if skill is None or skill['state'] != 'published':
            raise FakeProviderError('skill_version_unavailable')
        used = self.quota_charges.get(session_id, 0)
        if used + 1 > quota['limit']:
            raise FakeProviderError('quota_exceeded')
        self.quota_charges[session_id] = used + 1
        self.tasks[task_id] = {
            'id': task_id,
            'session_id': session_id,
            'idempotency_key': key,
            'skill_version_id': skill_version_id,
            'state': state,
            'next_card': next_card,
            'revision': 1,
            'created_at': '2026-11-24T00:00:00Z',
            'updated_at': '2026-11-24T00:00:00Z',
            'answers': {},
        }
        self.task_keys[index] = task_id
        return self._task_result(self.tasks[task_id], replayed=False)

    def get_task(self, task_id, session_id):
        self.events.append('get_task')
        self._maybe_fail('get_task')
        return deepcopy(self._owned_task(task_id, session_id))

    def get_published_skill(self):
        self.events.append('get_published_skill')
        self._maybe_fail('get_published_skill')
        published = [row for row in self.skill_versions.values() if row['state'] == 'published']
        if not published:
            raise FakeProviderError('skill_version_unavailable')
        return deepcopy(sorted(published, key=lambda row: row['version'])[-1])

    def list_tasks(self, session_id, limit=50, offset=0):
        self.events.append('list_tasks')
        self._maybe_fail('list_tasks')
        rows = [row for row in self.tasks.values() if row['session_id'] == session_id]
        return deepcopy(rows[offset:offset + limit])

    def get_task_aggregate(self, task_id, session_id):
        self.events.append('get_task_aggregate')
        self._maybe_fail('get_task_aggregate')
        return deepcopy(self._owned_task(task_id, session_id))

    def list_artifacts(self, task_id, session_id):
        self.events.append('list_artifacts')
        self._maybe_fail('list_artifacts')
        self._owned_task(task_id, session_id)
        return deepcopy([
            item for (task, _), item in self.artifacts.items() if task == task_id
        ])

    def _answer(self, card_id, task_id, session_id, expected_revision, value):
        operation = 'answer_' + card_id
        self.events.append(operation)
        self._maybe_fail(operation)
        self.answer_attempts += 1
        self.expected_revisions.append(expected_revision)
        if self.before_answer is not None:
            callback = self.before_answer
            self.before_answer = None
            callback(self)
        task = self._owned_task(task_id, session_id)
        if task['revision'] != expected_revision:
            raise FakeProviderError('revision_conflict')
        existing = task['answers'].get(card_id)
        if existing is not None:
            if existing == value:
                return {'task': deepcopy(task), 'changed': False}
            raise FakeProviderError('answer_conflict')
        task['answers'][card_id] = deepcopy(value)
        task['revision'] += 1
        return {'task': deepcopy(task), 'changed': True}

    def answer_direction(self, task_id, session_id, expected_revision, value):
        return self._answer('direction', task_id, session_id, expected_revision, value)

    def answer_mode(self, task_id, session_id, expected_revision, value):
        return self._answer('mode', task_id, session_id, expected_revision, value)

    def answer_terms(self, task_id, session_id, expected_revision, value):
        return self._answer('terms', task_id, session_id, expected_revision, value)

    def answer_years(self, task_id, session_id, expected_revision, value):
        return self._answer('years', task_id, session_id, expected_revision, value)

    def answer_adjustment(self, task_id, session_id, expected_revision, value):
        return self._answer('adjustment', task_id, session_id, expected_revision, value)

    def answer_delivery(self, task_id, session_id, expected_revision, value):
        return self._answer('delivery', task_id, session_id, expected_revision, value)

    def sync_task_state(self, task_id, session_id, expected_revision, state, next_card=None):
        self.events.append('sync_task_state')
        self._maybe_fail('sync_task_state')
        self.state_write_attempts += 1
        self.expected_revisions.append(expected_revision)
        if self.before_state_write is not None:
            callback = self.before_state_write
            self.before_state_write = None
            callback(self)
        task = self._owned_task(task_id, session_id)
        if task['revision'] != expected_revision:
            raise FakeProviderError('revision_conflict')
        task['state'] = state
        task['next_card'] = next_card
        task['revision'] += 1
        return deepcopy(task)

    def sync_artifacts(self, task_id, session_id, artifacts):
        self.events.append('sync_artifacts')
        self._maybe_fail('sync_artifacts')
        self._owned_task(task_id, session_id)
        saved = []
        for item in artifacts:
            checksum = item.get('checksum_sha256')
            metadata = {
                'task_id': task_id,
                'name': item['name'],
                'object_path': 'artifacts/%s/%s' % (task_id, item['name']),
                'size_bytes': item['size_bytes'],
                'content_type': item.get('content_type', 'application/octet-stream'),
                'checksum_sha256': checksum.lower() if isinstance(checksum, str) else None,
                'metadata': deepcopy(item.get('metadata') or {}),
            }
            self.artifacts[(task_id, item['name'])] = deepcopy(metadata)
            saved.append(metadata)
        return deepcopy(saved)


@pytest.fixture
def provider():
    return FakePrimaryStoreClient()


@pytest.fixture
def sync(provider):
    return TaskStoreSync(provider)


def bootstrap(sync):
    sync.sync_session('session-1', client_ip='127.0.0.1', user_agent='fake-agent')
    sync.sync_skill_version(SKILL_VERSION)


def create_task(sync, key='request-1'):
    return sync.create_task(
        session_id='session-1',
        task_id='task-1',
        idempotency_key=key,
        skill_version_id='skill-v1',
        quota=QUOTA,
    )


def test_session_and_skill_sync_preserve_identity_and_version(sync, provider):
    bootstrap(sync)

    assert provider.sessions['session-1'] == {
        'id': 'session-1',
        'client_ip': '127.0.0.1',
        'user_agent': 'fake-agent',
    }
    assert provider.skill_versions['skill-v1'] == SKILL_VERSION


def test_create_task_syncs_all_task_fields_and_charges_once(sync, provider):
    bootstrap(sync)

    task = create_task(sync)

    assert task == {
        'id': 'task-1',
        'session_id': 'session-1',
        'idempotency_key': 'request-1',
        'skill_version_id': 'skill-v1',
        'state': 'collecting_mode',
        'next_card': 'direction',
        'revision': 1,
        'created_at': '2026-11-24T00:00:00Z',
        'updated_at': '2026-11-24T00:00:00Z',
        'answers': {},
        'replayed': False,
    }
    assert provider.quota_charges == {'session-1': 1}


def test_duplicate_key_returns_current_original_without_quota_or_state_reset(sync, provider):
    bootstrap(sync)
    original = create_task(sync)
    sync.sync_task_state('session-1', original['id'], 'searching', next_card='years')

    replay = sync.create_task(
        session_id='session-1',
        task_id='different-retry-task',
        idempotency_key='request-1',
        skill_version_id='not-used-on-replay',
        quota={'limit': 1, 'window_seconds': 86400},
        state='done',
        next_card=None,
    )

    assert replay['replayed'] is True
    assert replay['id'] == original['id']
    assert replay['skill_version_id'] == original['skill_version_id']
    assert replay['state'] == 'searching'
    assert replay['next_card'] == 'years'
    assert replay['revision'] == 2
    assert len(provider.tasks) == 1
    assert provider.quota_charges == {'session-1': 1}


def test_authoritative_read_facades_validate_skill_tasks_answers_and_artifacts(sync, provider):
    bootstrap(sync)
    create_task(sync)
    sync.answer_card('session-1', 'task-1', 'direction', '肝癌免疫治疗耐药机制')
    sync.sync_artifacts('session-1', 'task-1', [{
        'name': 'report.docx',
        'size_bytes': 4,
        'content_type': 'application/octet-stream',
        'checksum_sha256': 'b' * 64,
        'metadata': {'kind': 'final'},
    }])

    assert sync.get_published_skill()['id'] == 'skill-v1'
    assert sync.get_task('session-1', 'task-1')['revision'] == 2
    aggregate = sync.get_task_aggregate('session-1', 'task-1')
    assert aggregate['answers']['direction'] == '肝癌免疫治疗耐药机制'
    assert [task['id'] for task in sync.list_tasks('session-1')] == ['task-1']
    artifacts = sync.list_artifacts('session-1', 'task-1')
    assert artifacts[0]['name'] == 'report.docx'
    assert artifacts[0]['checksum_sha256'] == 'b' * 64


def test_list_tasks_rejects_cross_owner_provider_row(sync, provider):
    bootstrap(sync)
    create_task(sync)
    provider.tasks['task-cross-owner'] = {
        'id': 'task-cross-owner',
        'session_id': 'someone-else',
        'revision': 1,
    }
    provider.list_tasks = lambda **kwargs: [deepcopy(provider.tasks['task-cross-owner'])]

    with pytest.raises(TaskStoreSyncError) as caught:
        sync.list_tasks('session-1')
    assert caught.value.code == 'invalid_provider_response'


def test_state_sync_reads_latest_remote_revision_before_conditional_write(sync, provider):
    bootstrap(sync)
    create_task(sync)
    provider.tasks['task-1'].update(state='adjusting', next_card='delivery', revision=7)
    provider.events.clear()

    updated = sync.sync_task_state('session-1', 'task-1', 'generating', next_card=None)

    assert provider.events == ['get_task', 'sync_task_state']
    assert provider.expected_revisions == [7]
    assert updated['state'] == 'generating'
    assert updated['revision'] == 8


def test_revision_conflict_does_not_overwrite_newer_remote_state(sync, provider):
    bootstrap(sync)
    create_task(sync)

    def concurrent_update(remote):
        remote.tasks['task-1'].update(state='done', next_card=None, revision=2)

    provider.before_state_write = concurrent_update
    with pytest.raises(TaskStoreRevisionConflict) as caught:
        sync.sync_task_state('session-1', 'task-1', 'searching', next_card='years')

    assert str(caught.value) == 'revision_conflict'
    assert provider.tasks['task-1']['state'] == 'done'
    assert provider.tasks['task-1']['revision'] == 2
    assert provider.state_write_attempts == 1
    assert provider.expected_revisions == [1]
    rendered = traceback.format_exc()
    assert all(fragment not in rendered for fragment in SENSITIVE_FRAGMENTS)


def test_answer_card_reads_latest_revision_and_preserves_replay_semantics(sync, provider):
    bootstrap(sync)
    create_task(sync)
    provider.events.clear()

    first = sync.answer_card('session-1', 'task-1', 'direction', '肝癌免疫治疗耐药机制')

    assert first['changed'] is True
    assert first['task']['revision'] == 2
    assert provider.events == ['get_task', 'answer_direction']
    assert provider.expected_revisions == [1]

    replay = sync.answer_card('session-1', 'task-1', 'direction', '肝癌免疫治疗耐药机制')
    assert replay['changed'] is False
    assert replay['task']['revision'] == 2
    assert provider.answer_attempts == 2
    assert provider.expected_revisions == [1, 2]


def test_answer_card_revision_conflict_does_not_overwrite_remote_answer(sync, provider):
    bootstrap(sync)
    create_task(sync)

    def concurrent_update(remote):
        remote.tasks['task-1']['revision'] = 2
        remote.tasks['task-1']['answers']['direction'] = 'newer answer'

    provider.before_answer = concurrent_update
    with pytest.raises(TaskStoreRevisionConflict):
        sync.answer_card('session-1', 'task-1', 'direction', 'stale answer')

    assert provider.answer_attempts == 1
    assert provider.tasks['task-1']['answers']['direction'] == 'newer answer'
    assert provider.tasks['task-1']['revision'] == 2


def test_answer_card_rejects_invalid_provider_decision(sync, provider):
    bootstrap(sync)
    create_task(sync)
    provider.answer_direction = lambda **kwargs: {'task': deepcopy(provider.tasks['task-1']), 'changed': 'yes'}

    with pytest.raises(TaskStoreSyncError) as caught:
        sync.answer_card('session-1', 'task-1', 'direction', 'direction')
    assert caught.value.code == 'invalid_provider_response'


def test_artifact_metadata_sync_is_task_scoped_and_complete(sync, provider):
    bootstrap(sync)
    create_task(sync)
    artifacts = [{
        'name': 'report.docx',
        'size_bytes': 1234,
        'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'checksum_sha256': 'B' * 64,
        'metadata': {'kind': 'final', 'verified': True},
    }]

    saved = sync.sync_artifacts('session-1', 'task-1', artifacts)

    assert saved[0]['task_id'] == 'task-1'
    assert saved[0]['name'] == 'report.docx'
    assert saved[0]['size_bytes'] == 1234
    assert saved[0]['checksum_sha256'] == 'b' * 64
    assert saved[0]['metadata'] == {'kind': 'final', 'verified': True}
    assert saved[0]['object_path'] == 'artifacts/task-1/report.docx'
    assert provider.artifacts[('task-1', 'report.docx')] == saved[0]


def _session_failure(sync):
    sync.sync_session('session-1')


def _skill_failure(sync):
    sync.sync_skill_version(SKILL_VERSION)


def _create_failure(sync):
    create_task(sync)


def _state_read_failure(sync):
    sync.sync_task_state('session-1', 'task-1', 'searching')


def _state_write_failure(sync):
    sync.sync_task_state('session-1', 'task-1', 'searching')


def _artifact_failure(sync):
    sync.sync_artifacts('session-1', 'task-1', [])


def _answer_failure(sync):
    sync.answer_card('session-1', 'task-1', 'direction', 'direction')


@pytest.mark.parametrize(
    'operation,call',
    [
        ('sync_session', _session_failure),
        ('sync_skill_version', _skill_failure),
        ('create_task', _create_failure),
        ('get_task', _state_read_failure),
        ('sync_task_state', _state_write_failure),
        ('sync_artifacts', _artifact_failure),
        ('answer_direction', _answer_failure),
    ],
)
def test_every_sync_boundary_redacts_sensitive_failures(sync, provider, operation, call):
    provider.sessions['session-1'] = {'id': 'session-1'}
    provider.skill_versions['skill-v1'] = deepcopy(SKILL_VERSION)
    provider.tasks['task-1'] = {
        'id': 'task-1',
        'session_id': 'session-1',
        'idempotency_key': 'request-1',
        'skill_version_id': 'skill-v1',
        'state': 'collecting_mode',
        'next_card': 'direction',
        'revision': 1,
    }
    provider.failures[operation] = RuntimeError(SENSITIVE_MESSAGE)

    with pytest.raises(TaskStoreSyncError) as caught:
        call(sync)

    assert caught.value.code == 'task_store_sync_failed'
    assert str(caught.value) == 'task_store_sync_failed'
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    rendered = '\n'.join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert all(fragment not in rendered for fragment in SENSITIVE_FRAGMENTS)
