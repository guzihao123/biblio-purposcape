from datetime import datetime, timezone

import pytest

from app.remote_recovery import recover_remote_interrupted, schedule_remote_retries


class RecoverySync:
    def __init__(self, status='started'):
        self.job = {
            'id': 'job-1', 'task_id': 'task-1', 'stage': 'generate',
            'input_hash': 'a' * 64, 'status': status, 'attempt': 1,
            'revision': 3 if status == 'failed' else 2,
            'task_revision': 2, 'lease_token': 'lease-1' if status == 'started' else None,
            'next_retry_at': '2020-01-01T00:00:00Z',
        }
        self.task = {
            'id': 'task-1', 'session_id': 'owner-1', 'skill_version_id': 'skill-1',
            'state': 'error' if status == 'failed' else 'generating',
            'next_card': None, 'revision': 2,
        }
        self.progress = {'checkpoint': None, 'updated_at': '2020-01-01T00:00:00Z'}
        self.calls = []

    def get_stage_job(self, session_id, task_id, job_id):
        return {
            'job': dict(self.job), 'task': dict(self.task),
            'progress': dict(self.progress), 'events': [], 'duplicate': False,
        }

    def complete_stage(self, **kwargs):
        self.calls.append(('complete', kwargs))
        self.job['status'] = 'completed'
        return self.get_stage_job(None, None, None)

    def fail_stage(self, **kwargs):
        self.calls.append(('fail', kwargs))
        self.job['status'] = 'failed'
        return self.get_stage_job(None, None, None)

    def retry_stage(self, **kwargs):
        self.calls.append(('retry', kwargs))
        if kwargs['max_attempts'] == 1:
            return dict(self.get_stage_job(None, None, None), exhausted=True)
        self.job.update(status='queued', revision=4)
        self.task['state'] = 'generating'
        return dict(self.get_stage_job(None, None, None), exhausted=False)


@pytest.fixture
def record():
    return {
        'task_id': 'task-1', 'stage': 'generate', 'session_id': 'owner-1',
        'job_id': 'job-1', 'input_hash': 'a' * 64,
    }


def test_interrupted_without_checkpoint_requires_manual_review(monkeypatch, record):
    remote = RecoverySync()
    monkeypatch.setattr('app.remote_recovery.configured_task_store_sync', lambda: remote)
    results = recover_remote_interrupted([record], now=lambda: datetime.now(timezone.utc))
    assert results[0]['action'] == 'manual_review'
    assert remote.calls[0][0] == 'fail'
    assert remote.calls[0][1]['event_type'] == 'recovery_manual_required'


def test_interrupted_checkpoint_settles_without_duplicate_execution(monkeypatch, record):
    remote = RecoverySync()
    remote.progress['checkpoint'] = {'stage': 'generate', 'clean': True}
    monkeypatch.setattr('app.remote_recovery.configured_task_store_sync', lambda: remote)
    results = recover_remote_interrupted([record], now=lambda: datetime.now(timezone.utc))
    assert results[0]['action'] == 'settled_checkpoint'
    assert remote.calls[0][0] == 'complete'
    assert remote.calls[0][1]['checkpoint'] == {'stage': 'generate', 'clean': True}


def test_failed_job_requeues_after_provider_claim(monkeypatch, record):
    remote = RecoverySync(status='failed')
    monkeypatch.setattr('app.remote_recovery.configured_task_store_sync', lambda: remote)
    enqueued = []
    monkeypatch.setattr('app.remote_recovery._enqueue', lambda item: enqueued.append(item))
    results = schedule_remote_retries([record])
    assert results[0]['action'] == 'requeued'
    assert enqueued == [record]
    assert remote.calls[0][0] == 'retry'


def test_exhausted_job_is_not_requeued(monkeypatch, record):
    remote = RecoverySync(status='failed')
    monkeypatch.setattr('app.remote_recovery.configured_task_store_sync', lambda: remote)
    monkeypatch.setattr(
        'app.remote_recovery._enqueue',
        lambda item: (_ for _ in ()).throw(AssertionError('must not enqueue')),
    )
    results = schedule_remote_retries([record], max_attempts=1)
    assert results[0]['action'] == 'retry_exhausted'
    assert len(remote.calls) == 1 and remote.calls[0][0] == 'retry'
