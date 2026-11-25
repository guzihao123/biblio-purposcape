import os
import sys
from pathlib import Path

from redis import Redis


sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend'))

from app.queueing import QUEUE_NAME, ProtectedWorker
from app.orchestration import register_stage_services
from app.recovery import start_recovery_scheduler


def main():
    redis_url = os.environ.get('REDIS_URL')
    if not redis_url:
        raise RuntimeError('REDIS_URL is required')
    connection = Redis.from_url(redis_url)
    register_stage_services()
    start_recovery_scheduler()
    ProtectedWorker([QUEUE_NAME], connection=connection).work()


if __name__ == '__main__':
    main()
