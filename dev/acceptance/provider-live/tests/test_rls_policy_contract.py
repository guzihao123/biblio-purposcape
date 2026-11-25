"""Static policy regressions; real behavior evidence is rls-verification-*.json."""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve()
MIGRATE = HERE.parents[1] / 'migrate_rls.py'


def load_migration():
    spec = importlib.util.spec_from_file_location('reviewed_rls_migration', MIGRATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unbound_session_insert_accepts_empty_guc_not_only_null():
    sql = load_migration().POLICY_SQL
    assert "current_setting('app.session_id', true) = ''" in sql
    assert "current_setting('app.session_id', true) IS NULL" not in sql


def test_sessions_have_no_self_update_policy_or_grant():
    migration = load_migration()
    assert 'sites_sessions_update' not in migration.POLICY_SQL
    source = MIGRATE.read_text(encoding='utf-8')
    assert 'REVOKE UPDATE ON sites_anonymous_sessions FROM app_user' in source
    assert 'sites_sessions_update' not in migration.POLICY_SQL


def test_business_reads_and_writes_require_active_session():
    sql = load_migration().POLICY_SQL
    for name in (
        'sites_tasks_owner_select',
        'sites_answers_owner_select',
        'sites_answers_owner_modify',
        'sites_artifacts_owner_select',
        'sites_artifacts_owner_modify',
        'sites_quota_owner_select',
    ):
        block = sql.split('CREATE POLICY ' + name, 1)[1].split(';', 1)[0]
        assert 'revoked_at IS NULL' in block
        assert 'expires_at IS NULL OR expires_at > now()' in block


def test_admin_has_only_policy_evaluation_reads_and_guard_checks_superuser():
    source = MIGRATE.read_text(encoding='utf-8')
    assert 'GRANT SELECT ON sites_anonymous_sessions, sites_tasks TO app_admin' in source
    assert 'GRANT SELECT ON sites_anonymous_sessions, sites_tasks, sites_task_answers' not in source
    assert 'migration_role_bypassrls_superuser_required' in source


def test_skill_reads_include_only_task_linked_nonpublished_versions():
    sql = load_migration().POLICY_SQL
    block = sql.split('CREATE POLICY sites_skill_read_published', 1)[1].split(';', 1)[0]
    assert 'sites_tasks.skill_version_id = sites_skill_versions.id' in block
    assert "sites_tasks.session_id = current_setting('app.session_id', true)" in block
    assert 'revoked_at IS NULL' in block


def test_stage_tables_have_owner_scoped_rls_and_role_grants():
    migration = load_migration()
    for table in ('sites_task_jobs', 'sites_task_progress', 'sites_task_events'):
        assert f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY' in migration.POLICY_SQL
        assert f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY' in migration.POLICY_SQL
        assert f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table}' in migration.POLICY_SQL or table in migration.TABLES
    for name in (
        'sites_jobs_owner_select', 'sites_jobs_owner_modify',
        'sites_progress_owner_select', 'sites_progress_owner_modify',
        'sites_events_owner_select', 'sites_events_owner_modify',
    ):
        block = migration.POLICY_SQL.split('CREATE POLICY ' + name, 1)[1].split(';', 1)[0]
        assert 'revoked_at IS NULL' in block
        assert 'expires_at IS NULL OR expires_at > now()' in block
