"""Expire abandoned confirmation tasks so the Skill active count can drain.

Only the three collection states wait for user input. A task left in one of
those states forever keeps ``SkillVersionService._assert_no_active_tasks``
from ever succeeding. Expiry is a pure state transition: answers, artifacts,
progress and prior events are kept, and no queue, quota or model operation is
performed.
"""

import os
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Task, TaskEvent

EXPIRABLE_TASK_STATES = (
    'collecting_mode',
    'collecting_terms',
    'collecting_years',
)
EXPIRED_STATE = 'error'
EXPIRED_EVENT_TYPE = 'task_expired'
EXPIRED_REASON = 'inactive_collection_timeout'
SAFETY_CATEGORY = 'safety'
EXPIRED_MESSAGE = '任务长时间无活动已过期，数据已保留；请重新发起任务继续调研。'
DEFAULT_IDLE_HOURS = 24
IDLE_HOURS_ENV = 'TASK_EXPIRY_HOURS'


def configured_idle_hours(environ=None):
    """Read the sweep threshold without changing the shared Settings model."""
    environ = os.environ if environ is None else environ
    raw = environ.get(IDLE_HOURS_ENV)
    if raw is None or str(raw).strip() == '':
        return DEFAULT_IDLE_HOURS
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        raise ValueError('%s must be a positive number' % IDLE_HOURS_ENV) from None
    if hours <= 0:
        raise ValueError('%s must be a positive number' % IDLE_HOURS_ENV)
    return int(hours) if hours.is_integer() else hours


def _utcnow():
    return datetime.now(timezone.utc)


def _updated_at(value):
    """Legacy SQLite rows can carry naive UTC timestamps."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def expire_idle_collection_tasks(
    session_factory=SessionLocal,
    now=None,
    idle_hours=None,
    dry_run=False,
):
    """Mark stale collection tasks as error/expired and record why.

    Returns one result per expired (or, in dry-run mode, expirable) task.
    Re-running the sweep cannot expire the same task twice because ``error``
    is outside ``EXPIRABLE_TASK_STATES``.
    """
    hours = configured_idle_hours() if idle_hours is None else idle_hours
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise ValueError('idle_hours must be a positive number')
    current = now() if now is not None else _utcnow()
    threshold_seconds = hours * 3600
    results = []

    with session_factory() as db:
        tasks = (
            db.query(Task)
            .filter(Task.state.in_(EXPIRABLE_TASK_STATES))
            .order_by(Task.id)
            .all()
        )
        for task in tasks:
            previous_state = task.state
            updated = _updated_at(task.updated_at)
            if updated is None:
                continue
            idle_seconds = max(0, int((current - updated).total_seconds()))
            if idle_seconds < threshold_seconds:
                continue

            reason_detail = (
                '任务处于 %s 状态且 %d 秒无活动，超过 %s 小时阈值'
                % (previous_state, idle_seconds, hours)
            )
            candidate = {
                'task_id': task.id,
                'session_id': task.session_id,
                'previous_state': previous_state,
                'state': EXPIRED_STATE,
                'updated_at': task.updated_at.isoformat(),
                'idle_seconds': idle_seconds,
                'idle_hours': round(idle_seconds / 3600, 2),
                'reason': EXPIRED_REASON,
                'detail': reason_detail,
                'event_type': EXPIRED_EVENT_TYPE,
                'dry_run': bool(dry_run),
            }
            if dry_run:
                results.append(candidate)
                continue

            # Conditional write: a task answered between the scan and the
            # write is left alone instead of being overwritten.
            changed = (
                db.query(Task)
                .filter(Task.id == task.id, Task.state == previous_state)
                .update(
                    {Task.state: EXPIRED_STATE, Task.updated_at: current},
                    synchronize_session=False,
                )
            )
            if not changed:
                continue

            db.add(TaskEvent(
                task_id=task.id,
                event_type=EXPIRED_EVENT_TYPE,
                payload={
                    'category': SAFETY_CATEGORY,
                    'reason': EXPIRED_REASON,
                    'detail': reason_detail,
                    'message': EXPIRED_MESSAGE,
                    'previous_state': previous_state,
                    'state': EXPIRED_STATE,
                    'marker': 'expired',
                    'updated_at': candidate['updated_at'],
                    'expired_at': current.isoformat(),
                    'idle_seconds': idle_seconds,
                    'idle_hours': candidate['idle_hours'],
                    'threshold_hours': hours,
                    'compute_charged': False,
                    'data_deleted': False,
                },
            ))
            results.append(candidate)

        if not dry_run:
            db.commit()
    return results
