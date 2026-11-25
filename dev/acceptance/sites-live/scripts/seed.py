"""Seed the isolated acceptance database with one published Skill version.

Runs offline against the dedicated sites-live SQLite file only. No cloud calls.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path('/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web')
DATA = ROOT / 'dev' / 'acceptance' / 'sites-live' / 'data'
DATA.mkdir(parents=True, exist_ok=True)

os.environ['DATABASE_URL'] = f'sqlite:///{DATA / "acceptance.db"}'
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6392/0')
os.environ['ARTIFACT_ROOT'] = str(DATA / 'artifacts')

sys.path.insert(0, str(ROOT / 'backend'))

from app.db import SessionLocal, initialize_database  # noqa: E402
from app.models import SkillVersion  # noqa: E402
from app.skill_versions import _hash, load_base_config  # noqa: E402

initialize_database()
with SessionLocal() as db:
    if db.query(SkillVersion).filter_by(state='published').one_or_none():
        print('published skill version already present; nothing to seed')
        sys.exit(0)
    content = load_base_config()
    version = SkillVersion(
        id=str(uuid4()),
        version=1,
        parent_id=None,
        state='published',
        content=content,
        content_hash=_hash(content),
        regression_report={'passed': True, 'checks': {}, 'errors': []},
        created_at=datetime.now(timezone.utc),
        published_at=datetime.now(timezone.utc),
    )
    db.add(version)
    db.commit()
    print(f'seeded published skill version id={version.id} version=1')
