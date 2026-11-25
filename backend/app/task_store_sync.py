"""Owner-scoped synchronization for the Qoder Sites primary task store.

This module is deliberately not wired into HTTP routes, workers, or migrations.
The injected client remains responsible for provider I/O, idempotency, quota
accounting, and conditional writes. Only fixed, non-sensitive error codes cross
this layer's public boundary.
"""

from functools import wraps


SAFE_PROVIDER_CODES = frozenset({
    'answer_conflict',
    'invalid_provider_response',
    'job_not_found',
    'quota_exceeded',
    'revision_conflict',
    'session_not_found',
    'skill_version_unavailable',
    'task_not_found',
    'task_store_unavailable',
    'worker_unauthorized',
})
# Kept for the private-name call sites in this module.
_SAFE_PROVIDER_CODES = SAFE_PROVIDER_CODES
_ANSWER_METHODS = {
    'direction': 'answer_direction',
    'mode': 'answer_mode',
    'terms': 'answer_terms',
    'years': 'answer_years',
    'adjustment': 'answer_adjustment',
    'delivery': 'answer_delivery',
}


class TaskStoreSyncError(RuntimeError):
    """Safe synchronization failure; provider details are never retained."""

    def __init__(self, code='task_store_sync_failed', retry_after=None):
        self.code = code if code in _SAFE_PROVIDER_CODES else 'task_store_sync_failed'
        if (
            isinstance(retry_after, bool) or not isinstance(retry_after, int) or
            not 1 <= retry_after <= 999_999_999
        ):
            retry_after = None
        self.retry_after = retry_after
        super().__init__(self.code)


class TaskStoreRevisionConflict(TaskStoreSyncError):
    """The remote task changed after its revision was read."""

    def __init__(self):
        super().__init__('revision_conflict')


def _safe_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except TaskStoreSyncError:
            raise
        except Exception as error:
            code = getattr(error, 'code', None)
            retry_after = getattr(error, 'retry_after', None)
            if code == 'revision_conflict':
                raise TaskStoreRevisionConflict() from None
            if code not in _SAFE_PROVIDER_CODES:
                code = 'task_store_sync_failed'
                retry_after = None
            raise TaskStoreSyncError(code, retry_after=retry_after) from None

    return wrapped


def _invalid_response():
    raise TaskStoreSyncError('invalid_provider_response')


def _valid_revision(value):
    return not isinstance(value, bool) and isinstance(value, int) and value >= 1


def _check_task(task, session_id, task_id=None):
    if not isinstance(task, dict):
        _invalid_response()
    if task.get('session_id') != session_id:
        _invalid_response()
    if task_id is not None and task.get('id') != task_id:
        _invalid_response()
    if not isinstance(task.get('id'), str) or not _valid_revision(task.get('revision')):
        _invalid_response()
    return task


def _check_stage_result(result, session_id, task_id, job_id=None, write=True):
    if not isinstance(result, dict):
        _invalid_response()
    _check_task(result.get('task'), session_id, task_id)
    job = result.get('job')
    if (
        not isinstance(job, dict) or job.get('task_id') != task_id or
        (job_id is not None and job.get('id') != job_id) or
        not _valid_revision(job.get('revision')) or
        not _valid_revision(job.get('task_revision')) or
        not isinstance(job.get('status'), str) or
        isinstance(job.get('attempt'), bool) or
        not isinstance(job.get('attempt'), int) or job['attempt'] < 0 or
        not isinstance(result.get('progress'), dict) or
        not isinstance(result.get('events'), list)
    ):
        _invalid_response()
    if write and not isinstance(result.get('duplicate'), bool):
        _invalid_response()
    return result


class TaskStoreSync:
    """Small synchronous facade over an injected ``SitesTaskStoreClient``.

    No credential, URL, SQL, provider body, or local path is accepted as an
    error message or logged. The caller supplies an already configured client.
    """

    def __init__(self, client):
        if client is None:
            raise ValueError('task store client is required')
        self._client = client

    @_safe_errors
    def sync_session(self, session_id, client_ip='', user_agent=''):
        """Create the remote anonymous session with the exact local identity."""
        remote_id = self._client.create_anonymous_session(
            client_ip=client_ip,
            user_agent=user_agent,
            session_id=session_id,
        )
        if remote_id != session_id:
            _invalid_response()
        return remote_id

    @_safe_errors
    def sync_skill_version(self, version):
        """Forward reviewed Skill fields and verify the saved version identity."""
        version_id = version.get('id') if isinstance(version, dict) else None
        saved = self._client.sync_skill_version(version)
        if not isinstance(saved, dict) or saved.get('id') != version_id:
            _invalid_response()
        for field in ('version', 'state', 'content_hash'):
            if field in version and saved.get(field) != version[field]:
                _invalid_response()
        return saved

    @_safe_errors
    def create_task(
        self,
        session_id,
        task_id,
        idempotency_key,
        skill_version_id,
        quota,
        state='collecting_mode',
        next_card='direction',
    ):
        """Create or replay a task without adding a second quota operation.

        A replay returns the authoritative stored task. Candidate task IDs,
        initial states, and Skill IDs from the retry never replace that record.
        """
        task = self._client.create_task(
            session_id=session_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            skill_version_id=skill_version_id,
            quota=quota,
            state=state,
            next_card=next_card,
        )
        _check_task(task, session_id)
        expected_key = idempotency_key.strip() if isinstance(idempotency_key, str) else None
        if task.get('idempotency_key') != expected_key:
            _invalid_response()
        replayed = task.get('replayed')
        if not isinstance(replayed, bool):
            _invalid_response()
        if not replayed and (
            task.get('id') != task_id or
            task.get('skill_version_id') != skill_version_id or
            task.get('state') != state or
            task.get('next_card') != next_card
        ):
            _invalid_response()
        return task

    @_safe_errors
    def get_published_skill(self):
        skill = self._client.get_published_skill()
        if (
            not isinstance(skill, dict) or skill.get('state') != 'published' or
            not isinstance(skill.get('id'), str) or not _valid_revision(skill.get('version'))
        ):
            _invalid_response()
        return skill

    @_safe_errors
    def get_session_record(self, session_id):
        session = self._client.get_session_record(session_id)
        if not isinstance(session, dict) or session.get('id') != session_id:
            _invalid_response()
        return session

    @_safe_errors
    def get_skill_version(self, session_id, skill_version_id):
        skill = self._client.get_skill_version(skill_version_id, session_id)
        if (
            not isinstance(skill, dict) or skill.get('id') != skill_version_id or
            not _valid_revision(skill.get('version')) or
            not isinstance(skill.get('content'), dict) or
            skill.get('state') not in {'draft', 'published', 'archived'}
        ):
            _invalid_response()
        return skill

    @_safe_errors
    def get_task(self, session_id, task_id):
        task = self._client.get_task(task_id=task_id, session_id=session_id)
        return _check_task(task, session_id, task_id)

    @_safe_errors
    def list_tasks(self, session_id, limit=50, offset=0):
        tasks = self._client.list_tasks(session_id=session_id, limit=limit, offset=offset)
        if not isinstance(tasks, list) or len(tasks) > limit:
            _invalid_response()
        seen = set()
        for task in tasks:
            _check_task(task, session_id)
            if task['id'] in seen:
                _invalid_response()
            seen.add(task['id'])
        return tasks

    @_safe_errors
    def get_task_aggregate(self, session_id, task_id):
        task = self._client.get_task_aggregate(task_id=task_id, session_id=session_id)
        _check_task(task, session_id, task_id)
        if not isinstance(task.get('answers'), dict):
            _invalid_response()
        return task

    @_safe_errors
    def list_artifacts(self, session_id, task_id):
        artifacts = self._client.list_artifacts(task_id=task_id, session_id=session_id)
        if not isinstance(artifacts, list):
            _invalid_response()
        seen = set()
        for item in artifacts:
            if (
                not isinstance(item, dict) or item.get('task_id') != task_id or
                not isinstance(item.get('name'), str) or not item['name'] or
                item['name'] in seen or
                isinstance(item.get('size_bytes'), bool) or
                not isinstance(item.get('size_bytes'), int) or item['size_bytes'] < 0 or
                not isinstance(item.get('metadata'), dict)
            ):
                _invalid_response()
            seen.add(item['name'])
        return artifacts

    @_safe_errors
    def answer_card(self, session_id, task_id, card_id, value):
        """Submit one card at the latest remote revision without retrying writes."""
        if card_id not in _ANSWER_METHODS:
            raise ValueError('invalid answer card')
        remote = self._client.get_task(task_id=task_id, session_id=session_id)
        _check_task(remote, session_id, task_id)
        revision = remote['revision']
        answer = getattr(self._client, _ANSWER_METHODS[card_id])(
            task_id=task_id,
            session_id=session_id,
            expected_revision=revision,
            value=value,
        )
        if not isinstance(answer, dict) or not isinstance(answer.get('changed'), bool):
            _invalid_response()
        task = answer.get('task')
        _check_task(task, session_id, task_id)
        expected = revision + 1 if answer['changed'] else revision
        if task['revision'] != expected:
            _invalid_response()
        return {'task': task, 'changed': answer['changed']}

    @_safe_errors
    def enqueue_stage(self, session_id, task_id, job_id, stage, input_hash, message):
        result = self._client.enqueue_stage(
            task_id=task_id, session_id=session_id, job_id=job_id,
            stage=stage, input_hash=input_hash, message=message,
        )
        _check_stage_result(result, session_id, task_id, job_id=None)
        job = result['job']
        if not result['duplicate'] and (
            job['id'] != job_id or job['stage'] != stage or
            job['input_hash'] != input_hash or job['status'] != 'queued' or
            job['revision'] != 1
        ):
            _invalid_response()
        return result

    @_safe_errors
    def start_stage(self, session_id, task_id, job_id, expected_job_revision, lease_token, message):
        result = self._client.start_stage(
            task_id=task_id, session_id=session_id, job_id=job_id,
            expected_job_revision=expected_job_revision,
            lease_token=lease_token, message=message,
        )
        _check_stage_result(result, session_id, task_id, job_id)
        if not result['duplicate'] and (
            result['job']['status'] != 'started' or
            result['job']['revision'] != expected_job_revision + 1 or
            result['job']['lease_token'] != lease_token
        ):
            _invalid_response()
        return result

    @_safe_errors
    def complete_stage(
        self, session_id, task_id, job_id, expected_job_revision, lease_token,
        state, next_card, message, checkpoint,
    ):
        result = self._client.complete_stage(
            task_id=task_id, session_id=session_id, job_id=job_id,
            expected_job_revision=expected_job_revision, lease_token=lease_token,
            state=state, next_card=next_card, message=message, checkpoint=checkpoint,
        )
        _check_stage_result(result, session_id, task_id, job_id)
        if not result['duplicate'] and (
            result['job']['status'] != 'completed' or
            result['job']['revision'] != expected_job_revision + 1 or
            result['task']['state'] != state or result['task']['next_card'] != next_card or
            result.get('checkpoint') != checkpoint
        ):
            _invalid_response()
        return result

    @_safe_errors
    def fail_stage(
        self, session_id, task_id, job_id, expected_job_revision, lease_token,
        event_type, message, protected_traceback=None, retry_after=None,
    ):
        result = self._client.fail_stage(
            task_id=task_id, session_id=session_id, job_id=job_id,
            expected_job_revision=expected_job_revision, lease_token=lease_token,
            event_type=event_type, message=message,
            protected_traceback=protected_traceback, retry_after=retry_after,
        )
        _check_stage_result(result, session_id, task_id, job_id)
        if not result['duplicate'] and (
            result['job']['status'] != 'failed' or
            result['job']['revision'] != expected_job_revision + 1 or
            result['task']['state'] != 'error'
        ):
            _invalid_response()
        return result

    @_safe_errors
    def retry_stage(self, session_id, task_id, job_id, expected_job_revision, message, max_attempts=3):
        result = self._client.retry_stage(
            task_id=task_id, session_id=session_id, job_id=job_id,
            expected_job_revision=expected_job_revision, message=message, max_attempts=max_attempts,
        )
        _check_stage_result(result, session_id, task_id, job_id, write=False)
        if not isinstance(result.get('exhausted'), bool):
            _invalid_response()
        if not result['exhausted'] and (
            result['job']['status'] != 'queued' or
            result['job']['revision'] != expected_job_revision + 1 or
            result['task']['state'] not in {'searching', 'generating'}
        ):
            _invalid_response()
        return result

    @_safe_errors
    def get_stage_job(self, session_id, task_id, job_id):
        result = self._client.get_stage_job(
            task_id=task_id, session_id=session_id, job_id=job_id,
        )
        return _check_stage_result(result, session_id, task_id, job_id, write=False)

    @_safe_errors
    def sync_task_state(self, session_id, task_id, state, next_card=None):
        """Read the current remote revision, then perform one conditional write.

        A concurrent revision change raises ``TaskStoreRevisionConflict``. This
        method deliberately does not retry, because doing so could overwrite a
        newer state without an application-level reconciliation decision.
        """
        remote = self._client.get_task(task_id=task_id, session_id=session_id)
        _check_task(remote, session_id, task_id)
        revision = remote['revision']
        updated = self._client.sync_task_state(
            task_id=task_id,
            session_id=session_id,
            expected_revision=revision,
            state=state,
            next_card=next_card,
        )
        _check_task(updated, session_id, task_id)
        if (
            updated.get('state') != state or
            updated.get('next_card') != next_card or
            updated.get('revision') != revision + 1
        ):
            _invalid_response()
        return updated

    @_safe_errors
    def get_latest_terms_event(self, session_id, task_id):
        event = self._client.get_latest_terms_event(task_id, session_id)
        if event is not None and (
            not isinstance(event, dict) or event.get('task_id') != task_id or
            event.get('event_type') not in {'terms_candidates', 'terms_candidates_unavailable'} or
            not isinstance(event.get('payload'), dict)
        ):
            _invalid_response()
        return event

    @_safe_errors
    def append_task_event(self, session_id, task_id, event_type, event_key, payload):
        event = self._client.append_task_event(task_id, session_id, event_type, event_key, payload)
        if (
            not isinstance(event, dict) or event.get('task_id') != task_id or
            event.get('event_type') != event_type or event.get('event_key') != event_key or
            event.get('payload') != payload
        ):
            _invalid_response()
        return event

    @_safe_errors
    def sync_artifacts(self, session_id, task_id, artifacts):
        """Synchronize artifact metadata only, preserving owner and task scope."""
        saved = self._client.sync_artifacts(
            task_id=task_id,
            session_id=session_id,
            artifacts=artifacts,
        )
        if not isinstance(saved, list) or not isinstance(artifacts, list) or len(saved) != len(artifacts):
            _invalid_response()
        by_name = {}
        for item in saved:
            if not isinstance(item, dict) or item.get('task_id') != task_id:
                _invalid_response()
            name = item.get('name')
            if not isinstance(name, str) or name in by_name:
                _invalid_response()
            by_name[name] = item
        for requested in artifacts:
            if not isinstance(requested, dict):
                _invalid_response()
            item = by_name.get(requested.get('name'))
            if item is None:
                _invalid_response()
            checksum = requested.get('checksum_sha256')
            expected = {
                'size_bytes': requested.get('size_bytes'),
                'content_type': requested.get('content_type', 'application/octet-stream'),
                'checksum_sha256': checksum.lower() if isinstance(checksum, str) else checksum,
                'metadata': requested.get('metadata') or {},
            }
            if any(item.get(field) != value for field, value in expected.items()):
                _invalid_response()
        return saved


def configured_task_store_sync():
    from app.config import get_settings
    from app.sites_task_store import SitesTaskStoreClient

    if get_settings().task_store_authority != 'sites':
        return None
    return TaskStoreSync(SitesTaskStoreClient.from_environment())
