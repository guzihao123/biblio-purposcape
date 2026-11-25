"""Fixed-path Python worker client for the Qoder Sites primary task store.

No method accepts SQL, a caller-supplied path, an arbitrary remote filter, or an
unscoped task query. The shared secret is used only in X-Worker-Token and is
redacted from representations and safe exceptions.
"""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit


_ID = re.compile(r'[A-Za-z0-9-]{1,64}\Z')
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_RETRY_AFTER = re.compile(r'[0-9]{1,9}\Z')
_STATES = {
    'collecting_mode', 'collecting_terms', 'collecting_years', 'searching',
    'dashboard_ready', 'adjusting', 'delivery_confirmed', 'generating',
    'verifying', 'done', 'error',
}
_CARDS = {'direction', 'mode', 'terms', 'years', 'adjustment', 'delivery'}
_ROOT = '/functions/v1/app/internal/task-store'


class SitesTaskStoreError(RuntimeError):
    """Safe error that never includes Provider bodies, URLs, or credentials."""

    def __init__(self, code='task_store_unavailable', status=None, retry_after=None):
        self.code = code
        self.status = status
        if (
            isinstance(retry_after, bool) or not isinstance(retry_after, int) or
            not 1 <= retry_after <= 999_999_999
        ):
            retry_after = None
        self.retry_after = retry_after
        super().__init__(code)


class SitesTaskStoreClient:
    def __init__(self, origin, shared_secret, transport=None, timeout=30):
        if not isinstance(origin, str):
            raise ValueError('Qoder Sites origin must use HTTPS')
        parsed = urlsplit(origin)
        local = parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.scheme == 'http'
        if (
            (parsed.scheme != 'https' and not local) or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise ValueError('Qoder Sites origin must use HTTPS')
        if not isinstance(shared_secret, str) or not shared_secret:
            raise ValueError('worker shared secret is required')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError('invalid worker timeout')
        self.origin = origin.rstrip('/')
        self._shared_secret = shared_secret
        self.transport = transport or self._request
        self.timeout = timeout

    def __repr__(self):
        return 'SitesTaskStoreClient(shared_secret=%r)' % '[redacted]'

    @classmethod
    def from_environment(cls, environ=None, transport=None, timeout=30):
        values = os.environ if environ is None else environ
        return cls(
            origin=values.get('QODER_SITES_ORIGIN', ''),
            shared_secret=values.get('WORKER_SHARED_SECRET', ''),
            transport=transport,
            timeout=timeout,
        )

    def _request(self, url, options):
        request = urllib.request.Request(
            url,
            data=options.get('body'),
            method=options.get('method', 'GET'),
            headers=options.get('headers') or {},
        )
        with urllib.request.urlopen(request, timeout=options.get('timeout', 30)) as response:
            body = response.read(2_000_001)
            content_type = response.headers.get('content-type', '')
        if len(body) > 2_000_000:
            raise SitesTaskStoreError('worker_response_too_large')
        if 'application/json' not in content_type:
            raise SitesTaskStoreError('invalid_worker_response')
        return json.loads(body.decode('utf-8'))

    @staticmethod
    def _id(value, field):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError('invalid ' + field)
        return value

    @staticmethod
    def _metadata(item):
        if not isinstance(item, dict):
            raise ValueError('invalid artifact')
        name = item.get('name')
        if (
            not isinstance(name, str) or not name or len(name) > 255 or
            name in {'.', '..'} or '/' in name or '\\' in name or
            any(ord(character) < 32 for character in name)
        ):
            raise ValueError('invalid artifact name')
        size = item.get('size_bytes')
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 50_000_000:
            raise ValueError('invalid artifact size')
        content_type = item.get('content_type', 'application/octet-stream')
        if not isinstance(content_type, str) or len(content_type) > 255 or '/' not in content_type:
            raise ValueError('invalid artifact content type')
        checksum = item.get('checksum_sha256')
        if checksum is not None:
            if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum.lower()):
                raise ValueError('invalid artifact checksum')
            checksum = checksum.lower()
        metadata = item.get('metadata') or {}
        if not isinstance(metadata, dict):
            raise ValueError('invalid artifact metadata')
        try:
            encoded = json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))
        except (TypeError, ValueError):
            raise ValueError('invalid artifact metadata') from None
        if len(encoded.encode('utf-8')) > 16_384:
            raise ValueError('invalid artifact metadata')
        return {
            'name': name,
            'size_bytes': size,
            'content_type': content_type,
            'checksum_sha256': checksum,
            'metadata': metadata,
        }

    @staticmethod
    def _http_failure(error, method, path):
        # The fixed worker surface has exactly one failure per listed
        # (status, method, path); mapping keys off that allowlist never
        # requires reading the Provider response body.
        status = error.code
        if (
            method == 'POST' and path.startswith('%s/tasks/' % _ROOT) and
            re.search(r'/answers/(?:direction|mode|terms|years|adjustment|delivery)\Z', path)
        ):
            if status == 409:
                return SitesTaskStoreError('revision_conflict', status=status)
            if status == 422:
                return SitesTaskStoreError('answer_conflict', status=status)
        if (
            status == 409 and method == 'POST' and
            path.startswith('%s/tasks/' % _ROOT) and '/stage/' in path
        ):
            return SitesTaskStoreError('revision_conflict', status=status)
        if (
            status == 409 and method == 'PUT' and
            path.startswith('%s/tasks/' % _ROOT) and path.endswith('/state')
        ):
            return SitesTaskStoreError('revision_conflict', status=status)
        if status == 409 and method == 'POST' and path == '%s/tasks' % _ROOT:
            return SitesTaskStoreError('skill_version_unavailable', status=status)
        if status == 429 and method == 'POST' and path == '%s/tasks' % _ROOT:
            retry_after = None
            if error.headers is not None:
                header = error.headers.get('Retry-After')
                if isinstance(header, str) and _RETRY_AFTER.fullmatch(header.strip()):
                    retry_after = int(header.strip())
            return SitesTaskStoreError(
                'quota_exceeded', status=status, retry_after=retry_after,
            )
        if status == 404 and method == 'GET' and '/jobs/' in path:
            return SitesTaskStoreError('job_not_found', status=status)
        if status == 401:
            return SitesTaskStoreError('session_not_found', status=status)
        if status == 403:
            return SitesTaskStoreError('worker_unauthorized', status=status)
        return SitesTaskStoreError('task_store_unavailable', status=status)

    def _call(self, path, method, session_id=None, payload=None):
        # `path` is constructed exclusively by the fixed methods below.
        headers = {'X-Worker-Token': self._shared_secret}
        if session_id is not None:
            headers['X-Session-Id'] = self._id(session_id, 'session_id')
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(body) > 2_000_000:
                raise ValueError('worker request too large')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        try:
            result = self.transport(self.origin + path, {
                'method': method,
                'headers': headers,
                'body': body,
                'timeout': self.timeout,
            })
            if not isinstance(result, dict):
                raise SitesTaskStoreError('invalid_worker_response')
            return result
        except SitesTaskStoreError:
            raise
        except urllib.error.HTTPError as error:
            failure = self._http_failure(error, method, path)
        except Exception:
            # Custom transports and urllib errors can contain sensitive request
            # headers or Provider responses; none are chained or logged here.
            failure = SitesTaskStoreError('task_store_unavailable')
        # Raise outside the exception handlers so the Provider error is not even
        # retained as __context__; its body is never read or inspected.
        raise failure from None

    @staticmethod
    def _task(result):
        task = result.get('task')
        if not isinstance(task, dict):
            raise SitesTaskStoreError('invalid_worker_response')
        return task

    @staticmethod
    def _artifacts(result):
        artifacts = result.get('artifacts')
        if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
            raise SitesTaskStoreError('invalid_worker_response')
        return artifacts

    def create_anonymous_session(self, client_ip='', user_agent='', session_id=None):
        if not isinstance(client_ip, str) or len(client_ip) > 64 or not isinstance(user_agent, str):
            raise ValueError('invalid session metadata')
        payload = {
            'client_ip': client_ip,
            'user_agent': user_agent[:300],
        }
        if session_id is not None:
            payload['id'] = self._id(session_id, 'session_id')
        result = self._call('%s/sessions' % _ROOT, 'POST', payload=payload)
        session_id = result.get('id')
        if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
            raise SitesTaskStoreError('invalid_worker_response')
        return session_id

    def get_session_record(self, session_id):
        session_id = self._id(session_id, 'session_id')
        result = self._call('%s/sessions/%s' % (_ROOT, quote(session_id, safe='')), 'GET', session_id=session_id)
        if result.get('id') != session_id:
            raise SitesTaskStoreError('invalid_worker_response')
        return result

    def get_published_skill(self):
        result = self._call('%s/skill-versions/published' % _ROOT, 'GET')
        skill = result.get('skill_version')
        if not isinstance(skill, dict) or skill.get('state') != 'published':
            raise SitesTaskStoreError('invalid_worker_response')
        return skill

    def get_skill_version(self, skill_version_id, session_id):
        skill_version_id = self._id(skill_version_id, 'skill_version_id')
        session_id = self._id(session_id, 'session_id')
        result = self._call(
            '%s/skill-versions/%s' % (_ROOT, quote(skill_version_id, safe='')),
            'GET', session_id=session_id,
        )
        skill = result.get('skill_version')
        if not isinstance(skill, dict) or skill.get('id') != skill_version_id:
            raise SitesTaskStoreError('invalid_worker_response')
        return skill

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
        session_id = self._id(session_id, 'session_id')
        skill_version_id = self._id(skill_version_id, 'skill_version_id')
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 255:
            raise ValueError('invalid idempotency_key')
        if state not in _STATES:
            raise ValueError('invalid task state')
        if next_card is not None and next_card not in _CARDS:
            raise ValueError('invalid next card')
        if not isinstance(quota, dict):
            raise ValueError('invalid quota')
        for field in ('limit', 'window_seconds'):
            value = quota.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError('invalid quota')
        payload = {
            'session_id': session_id,
            'idempotency_key': idempotency_key.strip(),
            'skill_version_id': skill_version_id,
            'quota': quota,
            'state': state,
            'next_card': next_card,
        }
        if task_id is not None:
            payload['task_id'] = self._id(task_id, 'task_id')
        result = self._call('%s/tasks' % _ROOT, 'POST', payload=payload)
        task = self._task(result)
        task['replayed'] = bool(result.get('replayed'))
        return task

    def list_tasks(self, session_id, limit=50, offset=0):
        session_id = self._id(session_id, 'session_id')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('invalid limit')
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError('invalid offset')
        path = '%s/tasks' % _ROOT
        if limit != 50 or offset != 0:
            path += '?limit=%d&offset=%d' % (limit, offset)
        result = self._call(path, 'GET', session_id=session_id)
        tasks = result.get('tasks')
        if not isinstance(tasks, list) or not all(isinstance(item, dict) for item in tasks):
            raise SitesTaskStoreError('invalid_worker_response')
        return tasks

    def get_task(self, task_id, session_id):
        task_id = self._id(task_id, 'task_id')
        path = '%s/tasks/%s' % (_ROOT, quote(task_id, safe=''))
        return self._task(self._call(path, 'GET', session_id=session_id))

    def get_task_aggregate(self, task_id, session_id):
        task_id = self._id(task_id, 'task_id')
        path = '%s/tasks/%s/aggregate' % (_ROOT, quote(task_id, safe=''))
        return self._task(self._call(path, 'GET', session_id=session_id))

    def _answer_card(self, card_id, task_id, session_id, expected_revision, value):
        if card_id not in _CARDS:
            raise ValueError('invalid answer card')
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        if (
            isinstance(expected_revision, bool) or
            not isinstance(expected_revision, int) or expected_revision < 1
        ):
            raise ValueError('invalid expected_revision')
        path = '%s/tasks/%s/answers/%s' % (_ROOT, quote(task_id, safe=''), card_id)
        result = self._call(path, 'POST', payload={
            'session_id': session_id,
            'expected_revision': expected_revision,
            'value': value,
        })
        task = self._task(result)
        if not isinstance(result.get('changed'), bool):
            raise SitesTaskStoreError('invalid_worker_response')
        return {'task': task, 'changed': result['changed']}

    def answer_direction(self, task_id, session_id, expected_revision, value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2000:
            raise ValueError('invalid direction')
        return self._answer_card('direction', task_id, session_id, expected_revision, value)

    def answer_mode(self, task_id, session_id, expected_revision, value):
        return self._answer_card('mode', task_id, session_id, expected_revision, value)

    def answer_terms(self, task_id, session_id, expected_revision, value):
        return self._answer_card('terms', task_id, session_id, expected_revision, value)

    def answer_years(self, task_id, session_id, expected_revision, value):
        return self._answer_card('years', task_id, session_id, expected_revision, value)

    def answer_adjustment(self, task_id, session_id, expected_revision, value):
        return self._answer_card('adjustment', task_id, session_id, expected_revision, value)

    def answer_delivery(self, task_id, session_id, expected_revision, value):
        return self._answer_card('delivery', task_id, session_id, expected_revision, value)

    def sync_task_state(self, task_id, session_id, expected_revision, state, next_card=None):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        if (
            isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or
            expected_revision < 1
        ):
            raise ValueError('invalid expected_revision')
        if state not in _STATES:
            raise ValueError('invalid task state')
        if next_card is not None and next_card not in _CARDS:
            raise ValueError('invalid next card')
        path = '%s/tasks/%s/state' % (_ROOT, quote(task_id, safe=''))
        result = self._call(path, 'PUT', payload={
            'session_id': session_id,
            'expected_revision': expected_revision,
            'state': state,
            'next_card': next_card,
        })
        return self._task(result)

    @staticmethod
    def _stage_result(result, write=True):
        if not isinstance(result, dict):
            raise SitesTaskStoreError('invalid_worker_response')
        job = result.get('job')
        task = result.get('task')
        progress = result.get('progress')
        events = result.get('events')
        if (
            not isinstance(job, dict) or not isinstance(task, dict) or
            not isinstance(progress, dict) or not isinstance(events, list) or
            not isinstance(job.get('id'), str) or not isinstance(job.get('task_id'), str) or
            not isinstance(job.get('revision'), int) or job['revision'] < 1 or
            not isinstance(job.get('task_revision'), int) or job['task_revision'] < 1
        ):
            raise SitesTaskStoreError('invalid_worker_response')
        if write and not isinstance(result.get('duplicate'), bool):
            raise SitesTaskStoreError('invalid_worker_response')
        return result

    def _stage_call(self, action, task_id, session_id, payload, write=True):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        path = '%s/tasks/%s/stage/%s' % (_ROOT, quote(task_id, safe=''), action)
        payload = dict(payload, session_id=session_id)
        return self._stage_result(self._call(path, 'POST', payload=payload), write=write)

    def enqueue_stage(self, task_id, session_id, job_id, stage, input_hash, message):
        job_id = self._id(job_id, 'job_id')
        if stage not in {'search', 'generate'}:
            raise ValueError('invalid stage')
        if not isinstance(input_hash, str) or not _SHA256.fullmatch(input_hash):
            raise ValueError('invalid input_hash')
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError('invalid stage message')
        return self._stage_call('enqueue', task_id, session_id, {
            'job_id': job_id, 'stage': stage, 'input_hash': input_hash, 'message': message,
        })

    def start_stage(self, task_id, session_id, job_id, expected_job_revision, lease_token, message):
        job_id = self._id(job_id, 'job_id')
        lease_token = self._id(lease_token, 'lease_token')
        if (
            isinstance(expected_job_revision, bool) or
            not isinstance(expected_job_revision, int) or expected_job_revision < 1
        ):
            raise ValueError('invalid expected_job_revision')
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError('invalid stage message')
        return self._stage_call('start', task_id, session_id, {
            'job_id': job_id, 'expected_job_revision': expected_job_revision,
            'lease_token': lease_token, 'message': message,
        })

    def complete_stage(
        self, task_id, session_id, job_id, expected_job_revision, lease_token,
        state, next_card, message, checkpoint,
    ):
        job_id = self._id(job_id, 'job_id')
        lease_token = self._id(lease_token, 'lease_token')
        if (
            isinstance(expected_job_revision, bool) or
            not isinstance(expected_job_revision, int) or expected_job_revision < 1
        ):
            raise ValueError('invalid expected_job_revision')
        if state not in _STATES:
            raise ValueError('invalid task state')
        if next_card is not None and next_card not in _CARDS:
            raise ValueError('invalid next card')
        if not isinstance(message, str) or len(message) > 500 or not isinstance(checkpoint, dict):
            raise ValueError('invalid stage completion')
        return self._stage_call('complete', task_id, session_id, {
            'job_id': job_id, 'expected_job_revision': expected_job_revision,
            'lease_token': lease_token, 'state': state, 'next_card': next_card,
            'message': message, 'checkpoint': checkpoint,
        })

    def fail_stage(
        self, task_id, session_id, job_id, expected_job_revision, lease_token,
        event_type, message, protected_traceback=None, retry_after=None,
    ):
        job_id = self._id(job_id, 'job_id')
        if lease_token is not None:
            lease_token = self._id(lease_token, 'lease_token')
        if (
            isinstance(expected_job_revision, bool) or
            not isinstance(expected_job_revision, int) or expected_job_revision < 1
        ):
            raise ValueError('invalid expected_job_revision')
        if event_type not in {'failed', 'rate_limited', 'enqueue_failed', 'recovery_manual_required'}:
            raise ValueError('invalid event type')
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError('invalid stage message')
        if protected_traceback is not None and not isinstance(protected_traceback, str):
            raise ValueError('invalid protected traceback')
        if (
            retry_after is not None and
            (isinstance(retry_after, bool) or not isinstance(retry_after, int) or retry_after < 1)
        ):
            raise ValueError('invalid retry_after')
        return self._stage_call('fail', task_id, session_id, {
            'job_id': job_id, 'expected_job_revision': expected_job_revision,
            'lease_token': lease_token, 'event_type': event_type, 'message': message,
            'protected_traceback': protected_traceback, 'retry_after': retry_after,
        })

    def retry_stage(self, task_id, session_id, job_id, expected_job_revision, message, max_attempts=3):
        job_id = self._id(job_id, 'job_id')
        if (
            isinstance(expected_job_revision, bool) or
            not isinstance(expected_job_revision, int) or expected_job_revision < 1
        ):
            raise ValueError('invalid expected_job_revision')
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError('invalid stage message')
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError('invalid max_attempts')
        result = self._stage_call('retry', task_id, session_id, {
            'job_id': job_id, 'expected_job_revision': expected_job_revision,
            'message': message, 'max_attempts': max_attempts,
        }, write=False)
        if not isinstance(result.get('exhausted'), bool):
            raise SitesTaskStoreError('invalid_worker_response')
        return result

    def get_stage_job(self, task_id, session_id, job_id):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        job_id = self._id(job_id, 'job_id')
        path = '%s/tasks/%s/jobs/%s' % (_ROOT, quote(task_id, safe=''), quote(job_id, safe=''))
        result = self._call(path, 'GET', session_id=session_id)
        return self._stage_result(result, write=False)

    def get_latest_terms_event(self, task_id, session_id):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        result = self._call(
            '%s/tasks/%s/events/terms' % (_ROOT, quote(task_id, safe='')),
            'GET', session_id=session_id,
        )
        event = result.get('event')
        if event is not None and not isinstance(event, dict):
            raise SitesTaskStoreError('invalid_worker_response')
        return event

    def append_task_event(self, task_id, session_id, event_type, event_key, payload):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        if event_type not in {'terms_candidates', 'terms_candidates_unavailable'}:
            raise ValueError('invalid event type')
        if not isinstance(event_key, str) or not event_key or len(event_key) > 160:
            raise ValueError('invalid event key')
        if not isinstance(payload, dict):
            raise ValueError('invalid event payload')
        result = self._call(
            '%s/tasks/%s/events' % (_ROOT, quote(task_id, safe='')),
            'POST',
            payload={
                'session_id': session_id, 'event_type': event_type,
                'event_key': event_key, 'payload': payload,
            },
        )
        event = result.get('event')
        if not isinstance(event, dict):
            raise SitesTaskStoreError('invalid_worker_response')
        return event

    def list_artifacts(self, task_id, session_id):
        task_id = self._id(task_id, 'task_id')
        path = '%s/tasks/%s/artifacts' % (_ROOT, quote(task_id, safe=''))
        return self._artifacts(self._call(path, 'GET', session_id=session_id))

    def sync_artifacts(self, task_id, session_id, artifacts):
        task_id = self._id(task_id, 'task_id')
        session_id = self._id(session_id, 'session_id')
        if not isinstance(artifacts, list) or len(artifacts) > 1000:
            raise ValueError('invalid artifacts')
        metadata = [self._metadata(item) for item in artifacts]
        names = [item['name'] for item in metadata]
        if len(set(names)) != len(names):
            raise ValueError('duplicate artifact name')
        path = '%s/tasks/%s/artifacts' % (_ROOT, quote(task_id, safe=''))
        result = self._call(path, 'PUT', payload={
            'session_id': session_id,
            'artifacts': metadata,
        })
        return self._artifacts(result)

    def sync_skill_version(self, version):
        if not isinstance(version, dict):
            raise ValueError('invalid skill version')
        version_id = self._id(version.get('id'), 'skill_version_id')
        # Forward only the reviewed schema fields, never arbitrary client keys.
        allowed = {
            'id', 'version', 'parent_id', 'state', 'content', 'content_hash',
            'regression_report', 'created_at', 'published_at',
        }
        payload = {key: value for key, value in version.items() if key in allowed}
        path = '%s/skill-versions/%s' % (_ROOT, quote(version_id, safe=''))
        result = self._call(path, 'PUT', payload=payload)
        saved = result.get('skill_version')
        if not isinstance(saved, dict):
            raise SitesTaskStoreError('invalid_worker_response')
        return saved
