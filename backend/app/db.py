from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import uuid4

from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


settings = get_settings()


def normalize_database_url(url):
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if host.endswith('.pooler.supabase.com') and parts.port == 6543:
        # Long-lived workers are more stable on Supavisor session mode (5432)
        # than transaction mode (6543), which drops idle TLS connections.
        netloc = parts.netloc.rsplit(':', 1)[0] + ':5432'
        url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def engine_kwargs(url):
    if url.startswith('sqlite'):
        return {'connect_args': {'check_same_thread': False}}
    if url.startswith('postgresql+psycopg'):
        return {
            # Supavisor/pgbouncer pooling cannot safely reuse client-side prepared statements.
            # A bounded connect timeout prevents a dead pooler endpoint from pinning a worker.
            'connect_args': {'prepare_threshold': None, 'connect_timeout': 10},
            # Pooled TLS connections can die between checkouts; probe and recycle them.
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'pool_timeout': 30,
        }
    return {}


database_url = normalize_database_url(settings.database_url)
engine = create_engine(database_url, **engine_kwargs(database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_base_skill(bind=engine):
    from app.models import SkillVersion
    from app.skill_versions import _hash, load_base_config

    with Session(bind=bind) as db:
        if db.query(SkillVersion).count():
            return
        content = load_base_config()
        now = datetime.now(timezone.utc)
        db.add(SkillVersion(
            id=str(uuid4()),
            version=1,
            parent_id=None,
            state='published',
            content=content,
            content_hash=_hash(content),
            regression_report={'passed': True, 'checks': {}, 'errors': []},
            created_at=now,
            published_at=now,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()


def initialize_database(bind=engine):
    from app.models import Base

    Base.metadata.create_all(bind=bind)
    task_columns = {column['name'] for column in inspect(bind).get_columns('tasks')}
    with bind.begin() as connection:
        if 'state' not in task_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN state VARCHAR(32) NOT NULL DEFAULT 'collecting_mode'")
            )
        if 'next_card' not in task_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN next_card VARCHAR(32) DEFAULT 'direction'")
            )
        if 'idempotency_key' not in task_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN idempotency_key VARCHAR(255)")
            )
        if 'skill_version_id' not in task_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN skill_version_id VARCHAR(36)")
            )
        if 'created_at' not in task_columns:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN created_at DATETIME"))
        if 'updated_at' not in task_columns:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN updated_at DATETIME"))
        progress_columns = {column['name'] for column in inspect(bind).get_columns('task_progress')}
        if 'updated_at' not in progress_columns:
            connection.execute(text("ALTER TABLE task_progress ADD COLUMN updated_at DATETIME"))
        if 'percent' not in progress_columns:
            connection.execute(text("ALTER TABLE task_progress ADD COLUMN percent INTEGER DEFAULT 0"))
        connection.execute(text("UPDATE task_progress SET percent = 0 WHERE percent IS NULL"))
        session_columns = {column['name'] for column in inspect(bind).get_columns('invite_sessions')}
        if 'client_ip' not in session_columns:
            connection.execute(
                text("ALTER TABLE invite_sessions ADD COLUMN client_ip VARCHAR(64) NOT NULL DEFAULT ''")
            )
        if 'user_agent' not in session_columns:
            connection.execute(
                text("ALTER TABLE invite_sessions ADD COLUMN user_agent VARCHAR(300) NOT NULL DEFAULT ''")
            )
        timestamp_type = DateTime(timezone=True).compile(dialect=bind.dialect)
        if 'expires_at' not in session_columns:
            connection.execute(
                text(f'ALTER TABLE invite_sessions ADD COLUMN expires_at {timestamp_type}')
            )
        if 'revoked_at' not in session_columns:
            connection.execute(
                text(f'ALTER TABLE invite_sessions ADD COLUMN revoked_at {timestamp_type}')
            )
        legacy_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=get_settings().session_ttl_seconds
        )
        connection.execute(
            text('UPDATE invite_sessions SET expires_at = :expires_at WHERE expires_at IS NULL'),
            {'expires_at': legacy_expiry},
        )

        # Legacy rows and partially upgraded empty strings remain valid: SQL
        # unique indexes permit multiple NULLs, so only explicit client keys are
        # deduplicated. Existing version/timestamp columns are left untouched.
        connection.execute(
            text("UPDATE tasks SET idempotency_key = NULL WHERE idempotency_key = ''")
        )
        connection.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_session_idempotency_key '
                'ON tasks (session_id, idempotency_key)'
            )
        )
    if get_settings().seed_base_skill:
        seed_base_skill(bind)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
