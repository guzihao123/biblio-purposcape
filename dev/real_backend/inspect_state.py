import json
import os
from pathlib import Path

import redis
from rq import Queue
from rq.worker import Worker
from sqlalchemy import create_engine, text

engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as connection:
    tasks = [dict(row._mapping) for row in connection.execute(text('select id, session_id, state, next_card from tasks order by created_at'))]
    jobs = [dict(row._mapping) for row in connection.execute(text('select task_id, kind, status from task_jobs order by task_id, kind'))]
    events = [dict(row._mapping) for row in connection.execute(text('select task_id, event_type, count(*) as count from task_events group by task_id, event_type order by task_id, event_type'))]
    versions = [dict(row._mapping) for row in connection.execute(text('select id, version, state, parent_id from skill_versions order by version'))]
    integrity = connection.execute(text('pragma integrity_check')).scalar_one()
connection = redis.Redis.from_url(os.environ['REDIS_URL'])
queue = Queue('landscape', connection=connection)
summary = {
    'database_integrity': integrity,
    'tasks': tasks,
    'jobs': jobs,
    'events': events,
    'skill_versions': versions,
    'redis_ping': bool(connection.ping()),
    'rq_queue': queue.name,
    'rq_queued_count': queue.count,
    'rq_workers': [worker.name for worker in Worker.all(connection=connection)],
    'artifact_directories': sorted(path.name for path in Path(os.environ['ARTIFACT_ROOT']).iterdir() if path.is_dir()),
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
