"""Offline authoritative vertical slice; no SQLite and no real Provider."""
import os
import subprocess
import sys
import time

import pytest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
sys.path.insert(0, BACKEND)

from app.sites_task_store import SitesTaskStoreClient, SitesTaskStoreError  # noqa: E402
from app.task_store_sync import TaskStoreSync  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 'http://127.0.0.1:8022'
SECRET = 'offline-slice-test-secret'


@pytest.fixture(scope='module')
def client():
    env = dict(os.environ, OFFLINE_WIRE_PORT='8022', OFFLINE_WORKER_SECRET=SECRET)
    if os.environ.get('OFFLINE_WIRE_RUNTIME') == 'deno':
        command = [
            os.environ.get('DENO_BIN', 'deno'), 'run', '--no-check',
            '--allow-read', '--allow-env', '--allow-net=127.0.0.1:8022',
            os.path.join(HERE, 'wire_server.mjs'),
        ]
    else:
        command = ['node', os.path.join(HERE, 'wire_server.mjs')]
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            line = proc.stdout.readline()
            if 'wire-server-ready' in line:
                break
            if not line:
                pytest.fail('wire server exited before ready')
        else:
            pytest.fail('wire server did not start')
        yield SitesTaskStoreClient(origin=ORIGIN, shared_secret=SECRET, timeout=15)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_authoritative_session_skill_task_direction_slice(client):
    session_id = 'slice-session-1'
    assert client.create_anonymous_session(
        client_ip='203.0.113.20',
        user_agent='offline-slice',
        session_id=session_id,
    ) == session_id
    assert client.get_session_record(session_id)['id'] == session_id

    skill = client.sync_skill_version({
        'id': 'slice-skill-1',
        'version': 1,
        'parent_id': None,
        'state': 'published',
        'content': {'cards': {}},
        'content_hash': 'a' * 64,
        'regression_report': {'passed': True},
        'created_at': '2026-11-24T00:00:00.000Z',
        'published_at': '2026-11-24T00:00:00.000Z',
    })
    assert skill['state'] == 'published'
    assert client.get_published_skill()['id'] == 'slice-skill-1'

    created = client.create_task(
        session_id=session_id,
        task_id='slice-task-1',
        idempotency_key='slice-idempotency-1',
        skill_version_id='slice-skill-1',
        quota={'limit': 5, 'window_seconds': 3600},
    )
    assert created['id'] == 'slice-task-1'
    assert created['revision'] == 1
    assert created['next_card'] == 'direction'
    assert client.get_task_aggregate('slice-task-1', session_id)['answers'] == {}

    direction = '肝癌免疫治疗耐药机制的最新进展'
    first = client.answer_direction('slice-task-1', session_id, 1, direction)
    assert first['changed'] is True
    assert first['task']['revision'] == 2
    assert first['task']['next_card'] == 'mode'
    assert first['task']['answers']['direction'] == direction

    replay = client.answer_direction('slice-task-1', session_id, 2, direction)
    assert replay['changed'] is False
    assert replay['task']['revision'] == 2

    with pytest.raises(SitesTaskStoreError) as stale:
        client.answer_direction('slice-task-1', session_id, 1, '旧 revision 写入')
    assert stale.value.code == 'revision_conflict'
    assert stale.value.status == 409

    with pytest.raises(SitesTaskStoreError) as conflict:
        client.answer_direction('slice-task-1', session_id, 2, '冲突方向')
    assert conflict.value.code == 'answer_conflict'
    assert conflict.value.status == 422

    aggregate = client.get_task_aggregate('slice-task-1', session_id)
    assert aggregate['revision'] == 2
    assert aggregate['next_card'] == 'mode'
    assert aggregate['answers'] == {'direction': direction}


def test_all_remaining_cards_over_real_http(client):
    session_id = 'slice-session-cards'
    skill_id = 'slice-skill-cards'
    task_id = 'slice-task-cards'
    assert client.create_anonymous_session(session_id=session_id) == session_id
    client.sync_skill_version({
        'id': skill_id,
        'version': 2,
        'parent_id': None,
        'state': 'published',
        'content': {'cards': {}},
        'content_hash': 'b' * 64,
        'regression_report': {'passed': True},
    })
    created = client.create_task(
        session_id=session_id,
        task_id=task_id,
        idempotency_key='slice-idempotency-cards',
        skill_version_id=skill_id,
        quota={'limit': 5, 'window_seconds': 3600},
    )
    assert created['revision'] == 1

    assert client.answer_direction(task_id, session_id, 1, '肝癌免疫治疗耐药机制')['task']['revision'] == 2
    assert client.answer_mode(task_id, session_id, 2, 'A')['task']['next_card'] == 'terms'
    assert client.answer_terms(task_id, session_id, 3, ['immunotherapy resistance'])['task']['next_card'] == 'years'
    assert client.answer_years(task_id, session_id, 4, {'choice': 'B'})['task']['state'] == 'searching'
    client.sync_task_state(task_id, session_id, 5, 'adjusting', next_card='adjustment')

    adjusted = client.answer_adjustment(
        task_id, session_id, 6, {'adjustment': ['years', 'mode']},
    )
    assert adjusted['changed'] is True
    assert adjusted['task']['revision'] == 7
    assert adjusted['task']['next_card'] == 'mode'
    assert adjusted['task']['answers']['adjustment'] == {'adjustment': ['mode', 'years']}
    assert client.answer_mode(task_id, session_id, 7, 'A')['task']['next_card'] == 'years'
    rerun = client.answer_years(task_id, session_id, 8, {'choice': 'B'})
    assert rerun['changed'] is True
    assert rerun['task']['state'] == 'searching'
    assert rerun['task']['revision'] == 9

    client.sync_task_state(task_id, session_id, 9, 'adjusting', next_card='adjustment')
    continued = client.answer_adjustment(
        task_id, session_id, 10, {'adjustment': ['terms', 'continue']},
    )
    assert continued['task']['next_card'] == 'delivery'
    assert continued['task']['answers']['adjustment'] == {'adjustment': ['continue']}
    delivered = client.answer_delivery(task_id, session_id, 11, {'form': 'B'})
    assert delivered['task']['revision'] == 12
    assert delivered['task']['state'] == 'generating'

    replay = client.answer_delivery(task_id, session_id, 12, {'form': 'B'})
    assert replay['changed'] is False
    assert replay['task']['revision'] == 12
    with pytest.raises(SitesTaskStoreError) as conflict:
        client.answer_delivery(task_id, session_id, 12, {'form': 'A'})
    assert conflict.value.code == 'answer_conflict'
    assert conflict.value.status == 422
    with pytest.raises(SitesTaskStoreError) as stale:
        client.answer_mode(task_id, session_id, 2, 'B')
    assert stale.value.code == 'revision_conflict'
    assert stale.value.status == 409

    aggregate = client.get_task_aggregate(task_id, session_id)
    assert aggregate['revision'] == 12
    assert aggregate['next_card'] is None
    assert aggregate['answers']['mode'] == {'mode': 'A'}
    assert aggregate['answers']['terms'] == ['immunotherapy resistance']
    assert aggregate['answers']['years'] == {'choice': 'B'}
    assert aggregate['answers']['delivery'] == {'form': 'B'}


def test_remote_stage_lifecycle_over_real_http(client):
    sync = TaskStoreSync(client)
    session_id = 'slice-session-stage'
    skill_id = 'slice-skill-stage'
    task_id = 'slice-task-stage'
    assert client.create_anonymous_session(session_id=session_id) == session_id
    sync.sync_skill_version({
        'id': skill_id,
        'version': 3,
        'parent_id': None,
        'state': 'published',
        'content': {'cards': {}},
        'content_hash': 'c' * 64,
        'regression_report': {'passed': True},
    })
    sync.create_task(
        session_id=session_id,
        task_id=task_id,
        idempotency_key='slice-stage-key',
        skill_version_id=skill_id,
        quota={'limit': 5, 'window_seconds': 3600},
    )
    queued = sync.enqueue_stage(
        session_id, task_id, 'slice-job-search', 'search', 'd' * 64, '等待检索',
    )
    assert queued['duplicate'] is False
    assert queued['job']['status'] == 'queued'
    replay = sync.enqueue_stage(
        session_id, task_id, 'slice-job-other-id', 'search', 'd' * 64, '等待检索',
    )
    assert replay['duplicate'] is True
    assert replay['job']['id'] == 'slice-job-search'

    started = sync.start_stage(
        session_id, task_id, 'slice-job-search', 1, 'slice-lease-search', '开始检索',
    )
    assert started['duplicate'] is False
    assert started['job']['attempt'] == 1
    duplicate_start = sync.start_stage(
        session_id, task_id, 'slice-job-search', 1, 'slice-other-lease', '开始检索',
    )
    assert duplicate_start['duplicate'] is True

    completed = sync.complete_stage(
        session_id, task_id, 'slice-job-search', 2, 'slice-lease-search',
        'dashboard_ready', 'adjustment', '检索完成', {'stage': 'search'},
    )
    assert completed['duplicate'] is False
    assert completed['task']['state'] == 'dashboard_ready'
    assert completed['checkpoint'] == {'stage': 'search'}
    duplicate_complete = sync.complete_stage(
        session_id, task_id, 'slice-job-search', 2, 'slice-lease-search',
        'dashboard_ready', 'adjustment', '检索完成', {'stage': 'search'},
    )
    assert duplicate_complete['duplicate'] is True
    current = sync.get_stage_job(session_id, task_id, 'slice-job-search')
    assert current['job']['status'] == 'completed'
    assert [event['event_type'] for event in current['events']] == [
        'queued', 'started', 'checkpoint', 'completed',
    ]

    sync.enqueue_stage(
        session_id, task_id, 'slice-job-generate', 'generate', 'e' * 64, '等待生成',
    )
    sync.start_stage(
        session_id, task_id, 'slice-job-generate', 1, 'slice-lease-generate', '开始生成',
    )
    failed = sync.fail_stage(
        session_id, task_id, 'slice-job-generate', 2, 'slice-lease-generate',
        'rate_limited', '请求过于频繁', 'safe traceback', retry_after=1,
    )
    assert failed['job']['status'] == 'failed'
    assert failed['job']['next_retry_at']
    assert failed['task']['state'] == 'error'
    assert failed['events'][-1]['payload']['retry_after'] == 1

    time.sleep(1.05)
    retried = sync.retry_stage(
        session_id, task_id, 'slice-job-generate', 3, '等待重试', max_attempts=3,
    )
    assert retried['exhausted'] is False
    assert retried['job']['status'] == 'queued'
    assert retried['job']['revision'] == 4
    assert retried['task']['state'] == 'generating'
    assert retried['events'][-1]['event_type'] == 'retry_scheduled'
