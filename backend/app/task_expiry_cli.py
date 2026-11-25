"""Manual idle-task expiry sweep.

Run from the repository root with the backend package on the path::

    PYTHONPATH=backend python -m app.task_expiry_cli --dry-run
    PYTHONPATH=backend python -m app.task_expiry_cli --hours 12

``--dry-run`` only lists candidates; it never writes to the task store.
"""

import argparse
import json

from app.task_expiry import (
    EXPIRABLE_TASK_STATES,
    configured_idle_hours,
    expire_idle_collection_tasks,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Expire stale collecting tasks')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='list expirable tasks without changing anything',
    )
    parser.add_argument(
        '--hours',
        type=float,
        default=None,
        help='idle threshold in hours (default: TASK_EXPIRY_HOURS env or 24)',
    )
    args = parser.parse_args(argv)

    hours = configured_idle_hours() if args.hours is None else args.hours
    tasks = expire_idle_collection_tasks(
        idle_hours=args.hours,
        dry_run=args.dry_run,
    )
    print(json.dumps({
        'dry_run': args.dry_run,
        'threshold_hours': hours,
        'eligible_states': list(EXPIRABLE_TASK_STATES),
        'count': len(tasks),
        'tasks': tasks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
