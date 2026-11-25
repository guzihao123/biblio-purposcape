"""The percent column is added in place, repeatably, without rewriting rows."""

from sqlalchemy import create_engine, text

from app.db import initialize_database
from app.models import Base, TaskProgress


LEGACY_PROGRESS_TABLE = """
CREATE TABLE task_progress (
    task_id VARCHAR(36) PRIMARY KEY,
    stage VARCHAR(64),
    message VARCHAR(500) NOT NULL DEFAULT '',
    input_hash VARCHAR(64),
    checkpoint JSON,
    protected_traceback TEXT
)
"""


def test_percent_migration_is_idempotent_and_preserves_legacy_rows(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-progress.db'}",
        connect_args={'check_same_thread': False},
    )
    with engine.begin() as connection:
        connection.execute(text(LEGACY_PROGRESS_TABLE))
        connection.execute(text(
            "INSERT INTO task_progress (task_id, stage, message) "
            "VALUES ('legacy-task', 'search', '检索与论文池整理完成')"
        ))

    initialize_database(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(task_progress)'))}
        assert 'percent' in columns
        migrated = connection.execute(text(
            "SELECT stage, message, percent FROM task_progress WHERE task_id = 'legacy-task'"
        )).one()
        assert migrated[0] == 'search'
        assert migrated[1] == '检索与论文池整理完成'
        assert migrated[2] == 0

    initialize_database(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(task_progress)'))}
        assert 'percent' in columns
        repeated = connection.execute(text(
            "SELECT message, percent FROM task_progress WHERE task_id = 'legacy-task'"
        )).one()
        assert repeated == ('检索与论文池整理完成', 0)
    engine.dispose()


def test_fresh_database_gets_percent_column_from_model(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh-progress.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(task_progress)'))}
        assert 'percent' in columns
        connection.execute(text(
            "INSERT INTO task_progress (task_id, message) VALUES ('fresh-task', '新任务')"
        ))
        value = connection.execute(text(
            "SELECT percent FROM task_progress WHERE task_id = 'fresh-task'"
        )).scalar()
        assert value == 0
    engine.dispose()


def test_null_percent_is_backfilled(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'nullable-progress.db'}")
    with engine.begin() as connection:
        connection.execute(text(LEGACY_PROGRESS_TABLE.replace(
            'protected_traceback TEXT', 'protected_traceback TEXT, percent INTEGER'
        )))
        connection.execute(text(
            "INSERT INTO task_progress (task_id, message, percent) VALUES ('null-task', '旧消息', NULL)"
        ))
    initialize_database(bind=engine)
    with engine.begin() as connection:
        value = connection.execute(text(
            "SELECT percent FROM task_progress WHERE task_id = 'null-task'"
        )).scalar()
        assert value == 0
    engine.dispose()
