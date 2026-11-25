from __future__ import annotations

import json

import psycopg

from migrate_rls import POLICY_SQL, RQ_SCHEMA_SQL, connection_parameters


POLICY_TABLES = {
    'sites_sessions_read': 'sites_anonymous_sessions',
    'sites_sessions_insert': 'sites_anonymous_sessions',
    'sites_sessions_update': 'sites_anonymous_sessions',
    'sites_skill_read_published': 'sites_skill_versions',
    'sites_skill_admin_write': 'sites_skill_versions',
    'sites_tasks_owner_select': 'sites_tasks',
    'sites_tasks_owner_insert': 'sites_tasks',
    'sites_tasks_owner_update': 'sites_tasks',
    'sites_answers_owner_select': 'sites_task_answers',
    'sites_answers_owner_modify': 'sites_task_answers',
    'sites_artifacts_owner_select': 'sites_task_artifacts',
    'sites_artifacts_owner_modify': 'sites_task_artifacts',
    'sites_quota_owner_select': 'sites_task_quota_windows',
    'sites_quota_owner_modify': 'sites_task_quota_windows',
    'sites_jobs_owner_select': 'sites_task_jobs',
    'sites_jobs_owner_modify': 'sites_task_jobs',
    'sites_progress_owner_select': 'sites_task_progress',
    'sites_progress_owner_modify': 'sites_task_progress',
    'sites_events_owner_select': 'sites_task_events',
    'sites_events_owner_modify': 'sites_task_events',
}


def main():
    with psycopg.connect(**connection_parameters()) as conn:
        with conn.transaction():
            conn.execute(RQ_SCHEMA_SQL)
            for policy, table in POLICY_TABLES.items():
                conn.execute(f'DROP POLICY IF EXISTS {policy} ON {table}')
            conn.execute(POLICY_SQL)
            conn.execute(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON sites_task_jobs, '
                'sites_task_progress, sites_task_events TO app_user'
            )
            conn.execute(
                'GRANT SELECT ON sites_task_jobs, sites_task_progress, sites_task_events TO audit_reader'
            )
            conn.execute('REVOKE UPDATE ON sites_anonymous_sessions FROM app_user')
            conn.execute(
                'REVOKE SELECT ON sites_anonymous_sessions, sites_tasks, '
                'sites_task_answers, sites_task_artifacts, sites_task_quota_windows FROM app_admin'
            )
            conn.execute('GRANT SELECT ON sites_anonymous_sessions, sites_tasks TO app_admin')
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_policies WHERE tablename = ANY(%s)",
                (list(set(POLICY_TABLES.values())),),
            )
            count = cur.fetchone()[0]
            if count != len(POLICY_TABLES) - 1:
                raise RuntimeError('unexpected_policy_count')
    print(json.dumps({'upgrade': 'passed', 'policies': count, 'data_deleted': False}))


if __name__ == '__main__':
    main()
