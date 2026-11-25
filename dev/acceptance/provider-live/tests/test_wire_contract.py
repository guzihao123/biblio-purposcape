"""Offline cross-stack wire acceptance for the Qoder Sites task store.

Real sites/functions/task_store.ts worker handler (fake-adapter backed) served
over real HTTP on 127.0.0.1:8021, exercised by the real Python
SitesTaskStoreClient with its real urllib transport -- no injected transport
fakes. These results are OFFLINE evidence: the database is an in-memory fake,
so they verify the fixed worker wire contract, not real Provider/PostgreSQL
permissions, RLS, or transactional atomicity.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
sys.path.insert(0, BACKEND)

from app.sites_task_store import SitesTaskStoreClient, SitesTaskStoreError  # noqa: E402
from app.task_store_sync import (  # noqa: E402
    TaskStoreRevisionConflict,
    TaskStoreSync,
    TaskStoreSyncError,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 'http://127.0.0.1:8021'
WORKER_SECRET = os.environ.get('OFFLINE_WORKER_SECRET', 'offline-wire-test-secret')
RUN_ID = os.environ.get('OFFLINE_RUN_ID', 'offline-wire-2026-11-24')
QUOTA = {'limit': 20, 'window_seconds': 86400}
HASH64 = 'a' * 64

FAKE_SECRET_FRAGMENTS = (
    'fake-db-secret-value',
    'SELECT * FROM private_table',
    '/private/local/path.db',
)


def rid(*parts):
    return '-'.join((RUN_ID,) + parts)


@pytest.fixture(scope='module')
def server():
    env = dict(os.environ, OFFLINE_WIRE_PORT='8021', OFFLINE_WORKER_SECRET=WORKER_SECRET)
    proc = subprocess.Popen(
        ['node', os.path.join(HERE, 'wire_server.mjs')],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    try:
        deadline = time.time() + 20
        ready = ''
        while time.time() < deadline:
            line = proc.stdout.readline()
            if 'wire-server-ready' in line:
                break
            if not line:
                pytest.fail('wire server exited before ready')
        else:
            pytest.fail('wire server did not start: %s' % ready)
        yield proc
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope='module')
def client(server):
    return SitesTaskStoreClient(origin=ORIGIN, shared_secret=WORKER_SECRET, timeout=15)


@pytest.fixture(scope='module')
def sync(client):
    return TaskStoreSync(client)


def raw(path, method='GET', body=None, token=WORKER_SECRET, session=None):
    headers = {}
    if token is not None:
        headers['X-Worker-Token'] = token
    if session is not None:
        headers['X-Session-Id'] = session
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    request = urllib.request.Request(
        ORIGIN + '/functions/v1/app/internal/task-store' + path,
        data=data, method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8')


def audit_quota(session_id):
    with urllib.request.urlopen(ORIGIN + '/offline-control/quota?session_id=' + session_id, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))['used']



def audit_session(session_id):
    with urllib.request.urlopen(ORIGIN + '/offline-control/session?id=' + session_id, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))

def audit_stats():
    with urllib.request.urlopen(ORIGIN + '/offline-control/stats', timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))


def publish_skill(client, skill_id, state='published'):
    return client.sync_skill_version({
        'id': skill_id,
        'version': 1,
        'parent_id': None,
        'state': state,
        'content': {'cards': {}},
        'content_hash': HASH64,
        'regression_report': {'passed': True},
    })


# ---------------------------------------------------------------------------
# WIRE-01: specified session id must survive the fixed worker boundary.
# ---------------------------------------------------------------------------

def test_wire01_fixed_session_id_preserved_end_to_end(server, client, sync):
    wanted = rid('wire01', 'session-a')
    assert sync.sync_session(wanted, client_ip='203.0.113.10', user_agent='wire-test') == wanted
    audited = audit_session(wanted)
    assert audited['id'] == wanted
    assert audited['client_ip'] == '203.0.113.10'

    # Anonymous behavior is preserved when no id is supplied.
    generated = client.create_anonymous_session()
    assert generated != wanted
    assert audit_session(generated)['id'] == generated


def test_wire01_illegal_session_id_rejected_without_side_effects(server, client):
    status, text = raw('/sessions', 'POST', {
        'client_ip': '', 'user_agent': '', 'id': 'has space',
    })
    assert status == 422
    assert json.loads(text) == {'error': 'invalid_session_id'}


# ---------------------------------------------------------------------------
# LIVE-ID-03 (offline analog): worker capability requires the worker token.
# ---------------------------------------------------------------------------

def test_worker_boundary_rejects_missing_and_wrong_token(server, client):
    status, text = raw('/tasks', 'GET', token=None, session=rid('id03', 's'))
    assert status == 403
    assert json.loads(text) == {'error': 'worker_unauthorized'}
    assert WORKER_SECRET not in text

    status, text = raw('/tasks', 'GET', token='wrong-token', session=rid('id03', 's'))
    assert status == 403
    assert json.loads(text) == {'error': 'worker_unauthorized'}


# ---------------------------------------------------------------------------
# LIVE-IDEM-01 (offline analog): concurrent same-key create, one winner.
# ---------------------------------------------------------------------------

def test_concurrent_same_key_create_single_task_single_charge(server, client, sync):
    session = client.create_anonymous_session()
    skill_id = rid('idem01', 'skill')
    publish_skill(sync._client, skill_id)
    key = rid('idem01', 'key')
    barrier = threading.Barrier(16)

    def create(_):
        barrier.wait(timeout=30)
        return sync.create_task(
            session_id=session,
            task_id=rid('idem01', 'candidate'),
            idempotency_key=key,
            skill_version_id=skill_id,
            quota=QUOTA,
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(create, range(16)))

    task_ids = {task['id'] for task in results}
    assert len(task_ids) == 1
    assert sum(1 for task in results if not task['replayed']) == 1
    assert all(task['session_id'] == session for task in results)
    assert len(sync._client.list_tasks(session)) == 1
    assert audit_quota(session) == 1


# ---------------------------------------------------------------------------
# LIVE-IDEM-02/03 (offline analog): replay preserves advanced state; the same
# key in another session is isolated.
# ---------------------------------------------------------------------------

def test_replay_preserves_advanced_state_and_owner_keys_are_isolated(server, sync):
    session_a = sync._client.create_anonymous_session()
    session_b = sync._client.create_anonymous_session()
    skill_id = rid('idem03', 'skill')
    publish_skill(sync._client, skill_id)
    shared_key = rid('idem03', 'shared-key')

    first = sync.create_task(
        session_id=session_a, task_id=rid('idem03', 'task-a'),
        idempotency_key=shared_key, skill_version_id=skill_id, quota=QUOTA,
    )
    advanced = sync.sync_task_state(session_a, first['id'], 'searching', next_card='terms')
    assert advanced['revision'] == 2

    replay = sync.create_task(
        session_id=session_a, task_id=rid('idem03', 'retry-candidate'),
        idempotency_key=shared_key, skill_version_id=skill_id,
        quota={'limit': 1, 'window_seconds': 60}, state='done', next_card=None,
    )
    assert replay['replayed'] is True
    assert replay['id'] == first['id']
    assert replay['state'] == 'searching'
    assert replay['next_card'] == 'terms'
    assert replay['revision'] == 2
    assert audit_quota(session_a) == 1

    other = sync.create_task(
        session_id=session_b, task_id=rid('idem03', 'task-b'),
        idempotency_key=shared_key, skill_version_id=skill_id, quota=QUOTA,
    )
    assert other['replayed'] is False
    assert other['id'] != first['id']
    assert audit_quota(session_b) == 1
    assert {task['id'] for task in sync._client.list_tasks(session_a)} == {first['id']}
    assert {task['id'] for task in sync._client.list_tasks(session_b)} == {other['id']}


# ---------------------------------------------------------------------------
# LIVE-ID-02 (offline analog): non-owner read/write/artifact access denied.
# ---------------------------------------------------------------------------

def test_non_owner_access_denied_without_leakage(server, sync):
    owner_a = sync._client.create_anonymous_session()
    owner_b = sync._client.create_anonymous_session()
    skill_id = rid('id02', 'skill')
    publish_skill(sync._client, skill_id)
    task = sync.create_task(
        session_id=owner_a, task_id=rid('id02', 'task'),
        idempotency_key=rid('id02', 'key'), skill_version_id=skill_id, quota=QUOTA,
    )
    sync.sync_artifacts(owner_a, task['id'], [{
        'name': 'report.docx', 'size_bytes': 16,
        'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'checksum_sha256': 'B' * 64, 'metadata': {'kind': 'final'},
    }])

    for status, _text in (
        raw('/tasks/%s' % task['id'], 'GET', session=owner_b),
        raw('/tasks/%s/artifacts' % task['id'], 'GET', session=owner_b),
        raw('/tasks/%s/state' % task['id'], 'PUT', session=owner_b, body={
            'session_id': owner_b, 'expected_revision': 1,
            'state': 'done', 'next_card': None,
        }),
        raw('/tasks/%s/artifacts' % task['id'], 'PUT', session=owner_b, body={
            'session_id': owner_b, 'artifacts': [{'name': 'evil.docx', 'size_bytes': 1}],
        }),
    ):
        assert status == 404

    current = sync._client.get_task(task['id'], owner_a)
    assert current['state'] == 'collecting_mode'
    assert current['revision'] == 1
    assert [item['name'] for item in sync._client.list_artifacts(task['id'], owner_a)] == ['report.docx']


# ---------------------------------------------------------------------------
# LIVE-ID-04 (offline analog): unpublished/missing Skill cannot create tasks.
# ---------------------------------------------------------------------------

def test_unpublished_or_missing_skill_cannot_create(server, sync):
    session = sync._client.create_anonymous_session()
    publish_skill(sync._client, rid('id04', 'draft-skill'), state='draft')
    publish_skill(sync._client, rid('id04', 'archived-skill'), state='archived')
    publish_skill(sync._client, rid('id04', 'pub-skill'))

    for skill_id in (rid('id04', 'draft-skill'), rid('id04', 'archived-skill'), rid('id04', 'missing')):
        status, text = raw('/tasks', 'POST', body={
            'session_id': session,
            'idempotency_key': rid('id04', 'key', skill_id[-12:]),
            'skill_version_id': skill_id,
            'quota': QUOTA,
        })
        assert status == 409
        assert json.loads(text) == {'error': 'skill_version_unavailable'}

    assert sync._client.list_tasks(session) == []
    assert audit_quota(session) == 0


# ---------------------------------------------------------------------------
# LIVE-TX-03 (offline analog): quota denial rolls the task insert back.
# ---------------------------------------------------------------------------

def test_quota_denial_rolls_back_task_and_reports_safe_client_error(server, sync):
    session = sync._client.create_anonymous_session()
    skill_id = rid('tx03', 'skill')
    publish_skill(sync._client, skill_id)
    tight = {'limit': 2, 'window_seconds': 86400}
    for index in range(2):
        sync.create_task(
            session_id=session, task_id=rid('tx03', 'task', str(index)),
            idempotency_key=rid('tx03', 'key', str(index)),
            skill_version_id=skill_id, quota=tight,
        )
    assert audit_quota(session) == 2

    status, text = raw('/tasks', 'POST', body={
        'session_id': session,
        'idempotency_key': rid('tx03', 'denied-key'),
        'skill_version_id': skill_id,
        'quota': tight,
    })
    assert status == 429
    assert json.loads(text)['error'] == 'quota_exceeded'

    with pytest.raises(TaskStoreSyncError) as caught:
        sync.create_task(
            session_id=session, task_id=rid('tx03', 'denied-task'),
            idempotency_key=rid('tx03', 'denied-key-2'),
            skill_version_id=skill_id, quota=tight,
        )
    # Fixed mapping: the server's safe `quota_exceeded` (429) survives the
    # real client with status and a validated retry_after.
    assert caught.value.code == 'quota_exceeded'
    assert caught.value.retry_after is not None
    assert isinstance(caught.value.retry_after, int)
    assert 1 <= caught.value.retry_after <= 86_400

    assert len(sync._client.list_tasks(session)) == 2
    assert audit_quota(session) == 2


def test_error_codes_survive_the_real_chain(server, sync):
    session = sync._client.create_anonymous_session()
    publish_skill(sync._client, rid('codes', 'draft'), state='draft')
    publish_skill(sync._client, rid('codes', 'pub'))

    with pytest.raises(TaskStoreSyncError) as caught:
        sync.create_task(
            session_id=session, task_id=rid('codes', 't1'),
            idempotency_key=rid('codes', 'k1'),
            skill_version_id=rid('codes', 'draft'), quota=QUOTA,
        )
    assert caught.value.code == 'skill_version_unavailable'

    with pytest.raises(TaskStoreSyncError) as caught:
        sync.create_task(
            session_id=rid('codes', 'missing-session'), task_id=rid('codes', 't2'),
            idempotency_key=rid('codes', 'k2'),
            skill_version_id=rid('codes', 'pub'), quota=QUOTA,
        )
    assert caught.value.code == 'session_not_found'

    for status, _text in (raw('/tasks', 'GET', token=None, session=session),):
        assert status == 403


# ---------------------------------------------------------------------------
# LIVE-REV-01/02/03 (offline analog): stale revision is rejected exactly once,
# mapped to TaskStoreRevisionConflict, and never overwrites the newer state.
# ---------------------------------------------------------------------------

def test_stale_revision_rejected_once_and_mapped_safely(server, sync):
    session = sync._client.create_anonymous_session()
    skill_id = rid('rev', 'skill')
    publish_skill(sync._client, skill_id)
    task = sync.create_task(
        session_id=session, task_id=rid('rev', 'task'),
        idempotency_key=rid('rev', 'key'), skill_version_id=skill_id, quota=QUOTA,
    )
    before = audit_stats()

    reader_revision = sync._client.get_task(task['id'], session)['revision']
    winner = sync.sync_task_state(session, task['id'], 'generating', next_card=None)
    assert winner['revision'] == reader_revision + 1

    with pytest.raises(SitesTaskStoreError) as caught:
        sync._client.sync_task_state(
            task_id=task['id'], session_id=session,
            expected_revision=reader_revision, state='error', next_card='delivery',
        )
    assert caught.value.code == 'revision_conflict'
    assert caught.value.__cause__ is None

    after = audit_stats()
    # The audit endpoint counts its own request: 4 real requests expected
    # (1 get_task + winner GET/PUT + exactly one stale PUT), proving the
    # stale conditional write is attempted once with no automatic retry.
    work_requests = (after['http_requests'] - before['http_requests']) - 1
    assert work_requests == 4
    current = sync._client.get_task(task['id'], session)
    assert current['state'] == 'generating'
    assert current['next_card'] is None
    assert current['revision'] == reader_revision + 1
    assert audit_quota(session) == 1

    # HTTP-level: the fixed boundary preserves 409 and a safe conflict body.
    status, text = raw('/tasks/%s/state' % task['id'], 'PUT', session=session, body={
        'session_id': session, 'expected_revision': reader_revision,
        'state': 'error', 'next_card': 'delivery',
    })
    assert status == 409
    assert json.loads(text) == {'error': 'revision_conflict'}


# ---------------------------------------------------------------------------
# LIVE-ART-01/02/03 (offline analog): artifact metadata scope and upsert.
# ---------------------------------------------------------------------------

def test_artifact_metadata_scope_upsert_and_non_owner_denial(server, sync):
    session_a = sync._client.create_anonymous_session()
    session_b = sync._client.create_anonymous_session()
    skill_id = rid('art', 'skill')
    publish_skill(sync._client, skill_id)
    task = sync.create_task(
        session_id=session_a, task_id=rid('art', 'task'),
        idempotency_key=rid('art', 'key'), skill_version_id=skill_id, quota=QUOTA,
    )

    m1 = [{
        'name': 'report.docx', 'size_bytes': 1024,
        'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'checksum_sha256': 'C' * 64, 'metadata': {'version': 1},
    }]
    saved = sync.sync_artifacts(session_a, task['id'], m1)
    assert saved[0]['object_path'] == 'artifacts/%s/report.docx' % task['id']
    created_at = saved[0]['created_at']

    repeated = sync.sync_artifacts(session_a, task['id'], m1)
    assert repeated[0]['created_at'] == created_at

    m2 = [dict(m1[0], size_bytes=2048, metadata={'version': 2})]
    updated = sync.sync_artifacts(session_a, task['id'], m2)
    assert updated[0]['size_bytes'] == 2048
    assert updated[0]['created_at'] == created_at
    assert len(sync._client.list_artifacts(task['id'], session_a)) == 1

    status, _text = raw('/tasks/%s/artifacts' % task['id'], 'GET', session=session_b)
    assert status == 404


# ---------------------------------------------------------------------------
# LIVE-SEC-01 (offline analog): injected Provider failure must not leak
# secrets, SQL, provider bodies, or local paths through the fixed surface.
# ---------------------------------------------------------------------------

def test_injected_provider_failure_is_sanitized_end_to_end(server, sync):
    session = sync._client.create_anonymous_session()
    skill_id = rid('sec01', 'skill')
    publish_skill(sync._client, skill_id)
    task = sync.create_task(
        session_id=session, task_id=rid('sec01', 'task'),
        idempotency_key=rid('sec01', 'key'), skill_version_id=skill_id, quota=QUOTA,
    )

    switch = os.path.join(HERE, 'fail-next.json')
    with open(switch, 'w', encoding='utf-8') as handle:
        json.dump({
            'operation': 'get_owned_task',
            'message': 'password=%s; SQL=%s; body at %s' % FAKE_SECRET_FRAGMENTS,
        }, handle)

    with pytest.raises(SitesTaskStoreError) as caught:
        sync._client.get_task(task['id'], session)
    assert caught.value.code == 'task_store_unavailable'
    rendered = str(caught.value) + repr(caught.value)
    assert all(fragment not in rendered for fragment in FAKE_SECRET_FRAGMENTS)

    status, text = raw('/tasks/%s' % task['id'], 'GET', session=session)
    # fail-next was consumed by the client call above; this read succeeds, so
    # re-inject to verify the raw HTTP error surface too.
    assert status == 200
    with open(switch, 'w', encoding='utf-8') as handle:
        json.dump({
            'operation': 'get_owned_task',
            'message': 'password=%s; SQL=%s; body at %s' % FAKE_SECRET_FRAGMENTS,
        }, handle)
    status, text = raw('/tasks/%s' % task['id'], 'GET', session=session)
    assert status == 503
    assert json.loads(text) == {'error': 'task_store_unavailable'}
    assert all(fragment not in text for fragment in FAKE_SECRET_FRAGMENTS)
    assert WORKER_SECRET not in text
