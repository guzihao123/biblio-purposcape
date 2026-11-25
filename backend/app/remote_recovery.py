"""Recovery driven by RQ registries and authoritative per-owner stage jobs."""

from datetime import datetime, timezone

import redis
from rq import Queue
from rq.job import Job
from rq.registry import FailedJobRegistry, StartedJobRegistry

from app.config import get_settings
from app.task_store_sync import configured_task_store_sync


def _now(now):
    return now() if now is not None else datetime.now(timezone.utc)


def _timestamp(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _records():
    from app.queueing import QUEUE_NAME

    url = get_settings().redis_url
    if not url:
        return {'started': [], 'failed': []}
    connection = redis.from_url(url)
    queue = Queue(QUEUE_NAME, connection=connection)
    result = {'started': [], 'failed': []}
    for name, registry in (
        ('started', StartedJobRegistry(queue)),
        ('failed', FailedJobRegistry(queue)),
    ):
        for rq_id in registry.get_job_ids():
            rq_job = Job.fetch(rq_id, connection=connection)
            if len(rq_job.args) < 2:
                continue
            task_id, stage = rq_job.args[:2]
            metadata = rq_job.kwargs or {}
            if metadata.get('session_id') and metadata.get('job_id'):
                result[name].append({
                    'task_id': task_id,
                    'stage': stage,
                    'session_id': metadata['session_id'],
                    'job_id': metadata['job_id'],
                    'input_hash': metadata.get('input_hash'),
                })
    return result


def _enqueue(record):
    from app.queueing import QueueAdapter, run_stage

    return QueueAdapter().queue.enqueue(
        run_stage,
        record['task_id'],
        record['stage'],
        session_id=record['session_id'],
        job_id=record['job_id'],
        input_hash=record.get('input_hash'),
    )


def recover_remote_interrupted(records, stale_after=3600, now=None, max_attempts=3):
    del max_attempts
    current_time = _now(now)
    sync = configured_task_store_sync()
    results = []
    for record in records:
        current = sync.get_stage_job(record['session_id'], record['task_id'], record['job_id'])
        if current['job']['status'] != 'started':
            continue
        updated = _timestamp(current['progress'].get('updated_at'))
        if updated is None or (current_time - updated).total_seconds() < stale_after:
            continue
        checkpoint = current['progress'].get('checkpoint')
        if checkpoint:
            sync.complete_stage(
                session_id=record['session_id'],
                task_id=record['task_id'],
                job_id=record['job_id'],
                expected_job_revision=current['job']['revision'],
                lease_token=current['job']['lease_token'],
                state='dashboard_ready' if record['stage'] == 'search' else 'done',
                next_card='adjustment' if record['stage'] == 'search' else None,
                message='已从检查点恢复，未重复执行检索或模型调用',
                checkpoint=checkpoint,
            )
            action = 'settled_checkpoint'
        else:
            sync.fail_stage(
                session_id=record['session_id'],
                task_id=record['task_id'],
                job_id=record['job_id'],
                expected_job_revision=current['job']['revision'],
                lease_token=current['job']['lease_token'],
                event_type='recovery_manual_required',
                message='执行中断，外部服务结果未确认，请人工复核后重试',
                protected_traceback=None,
            )
            action = 'manual_review'
        results.append({'task_id': record['task_id'], 'job_id': record['job_id'], 'action': action})
    return results


def schedule_remote_retries(records, max_attempts=3):
    sync = configured_task_store_sync()
    results = []
    for record in records:
        current = sync.get_stage_job(record['session_id'], record['task_id'], record['job_id'])
        if current['job']['status'] != 'failed':
            continue
        try:
            retried = sync.retry_stage(
                session_id=record['session_id'],
                task_id=record['task_id'],
                job_id=record['job_id'],
                expected_job_revision=current['job']['revision'],
                message='准备重试',
                max_attempts=max_attempts,
            )
        except Exception as error:
            if getattr(error, 'code', None) in {'retry_not_due', 'revision_conflict'}:
                continue
            raise
        if retried['exhausted']:
            results.append({'task_id': record['task_id'], 'job_id': record['job_id'], 'action': 'retry_exhausted'})
            continue
        _enqueue(record)
        results.append({'task_id': record['task_id'], 'job_id': record['job_id'], 'action': 'requeued'})
    return results


def run_remote_recovery_cycle(now=None, max_attempts=3):
    records = _records()
    return {
        'recovered': recover_remote_interrupted(records['started'], now=now, max_attempts=max_attempts),
        'requeued': schedule_remote_retries(records['failed'], max_attempts=max_attempts),
    }
