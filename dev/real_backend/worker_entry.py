import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from offline_providers import install

install()

from redis import Redis

from app.orchestration import register_stage_services
from app.queueing import QUEUE_NAME, ProtectedSimpleWorker
from app.recovery import start_recovery_scheduler


def main():
    connection = Redis.from_url(os.environ['REDIS_URL'])
    register_stage_services()
    start_recovery_scheduler()
    ProtectedSimpleWorker([QUEUE_NAME], connection=connection).work()


if __name__ == '__main__':
    main()
