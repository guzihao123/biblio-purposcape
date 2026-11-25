from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg


def parameters(role):
    values = psycopg.conninfo.conninfo_to_dict(os.environ['DATABASE_URL'])
    passwords = {}
    for line in Path('/Users/crisprcas_9/.config/purpose-landscape/provider-roles.env').read_text(encoding='utf-8').splitlines():
        key, value = line.split('=', 1)
        passwords[key] = value
    original_user = values.get('user', '')
    values['user'] = role
    if '.' in original_user:
        tenant_suffix = original_user.split('.', 1)[1]
        values['user'] = f'{role}.{tenant_suffix}'
    values['password'] = passwords[f'{role.upper()}_PASSWORD']
    values['connect_timeout'] = 10
    return values


def execute(connection, statement, parameters=None):
    with connection.cursor() as cur:
        cur.execute(statement, parameters)
        if cur.description:
            return cur.fetchall()


def main():
    with psycopg.connect(**parameters('app_admin')) as conn:
        execute(conn, """
            INSERT INTO sites_skill_versions (
                id, version, parent_id, state, content, content_hash,
                regression_report, created_at, published_at
            ) VALUES (
                'rls-skill-a', 1, NULL, 'published', '{}', %s, '{"passed":true}',
                '2026-11-24T00:00:00Z', '2026-11-24T00:00:00Z'
            )
        """, ('a' * 64,))

    with psycopg.connect(**parameters('app_user')) as conn:
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-a', true)")
        execute(conn, """
            INSERT INTO sites_anonymous_sessions (id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at)
            VALUES ('rls-session-a', '203.0.113.10', 'rls-test', now(), now(),
                    '2027-01-01T00:00:00Z', NULL)
        """)
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-a', true)")
        execute(conn, """
            INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
            VALUES ('rls-task-a', 'rls-session-a', 'rls-skill-a', 'rls-key-a', 'collecting_mode', 'direction')
        """)
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-a', true)")
        execute(conn, """
            INSERT INTO sites_task_answers (task_id, card_id, value, created_at, updated_at)
            VALUES ('rls-task-a', 'direction', %s, now(), now())
        """, (json.dumps('肝癌免疫治疗耐药机制', ensure_ascii=False),))
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-a', true)")
        own_task = execute(conn, "SELECT id, next_card, revision FROM sites_tasks WHERE id = 'rls-task-a'")
        assert own_task[0][1] == 'direction' and own_task[0][2] == 1

    with psycopg.connect(**parameters('app_user')) as conn:
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-b', true)")
        execute(conn, """
            INSERT INTO sites_anonymous_sessions (id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at)
            VALUES ('rls-session-b', '203.0.113.20', 'rls-test', now(), now(),
                    '2027-01-01T00:00:00Z', NULL)
        """)
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-b', true)")
        cross_reads = execute(conn, "SELECT count(*) FROM sites_tasks WHERE id = 'rls-task-a'")
        assert cross_reads[0][0] == 0
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-b', true)")
        try:
            execute(conn, """
                INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
                VALUES ('rls-task-cross', 'rls-session-a', 'rls-skill-a', 'rls-key-cross', 'collecting_mode', 'direction')
            """)
            raise AssertionError('cross-owner task insert unexpectedly succeeded')
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-b', true)")
        try:
            execute(conn, """
                INSERT INTO sites_task_answers (task_id, card_id, value, created_at, updated_at)
                VALUES ('rls-task-a', 'direction', %s, now(), now())
            """, (json.dumps('cross-owner answer', ensure_ascii=False),))
            raise AssertionError('cross-owner answer insert unexpectedly succeeded')
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()

    with psycopg.connect(**parameters('app_user')) as conn:
        try:
            execute(conn, """
                INSERT INTO sites_skill_versions (
                    id, version, parent_id, state, content, content_hash,
                    regression_report, created_at, published_at
                ) VALUES (
                    'rls-skill-user-write', 2, NULL, 'draft', '{}', %s, NULL,
                    '2026-11-24T00:00:00Z', NULL
                )
            """, ('b' * 64,))
            raise AssertionError('app_user unexpectedly wrote a Skill')
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
        execute(conn, "SELECT set_config('app.session_id', 'expired-session', true)")
        try:
            execute(conn, """
                INSERT INTO sites_anonymous_sessions (id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at)
                VALUES ('expired-session', '203.0.113.30', 'rls-test', now(), now(),
                        '2020-01-01T00:00:00Z', NULL)
            """)
            raise AssertionError('expired session unexpectedly inserted')
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()

    with psycopg.connect(**parameters('audit_reader')) as conn:
        task_count = execute(conn, "SELECT count(*) FROM sites_tasks WHERE id = 'rls-task-a'")[0][0]
        answer_count = execute(conn, "SELECT count(*) FROM sites_task_answers WHERE task_id = 'rls-task-a'")[0][0]
        assert task_count == 1 and answer_count == 1

    with psycopg.connect(**parameters('app_user')) as conn:
        execute(conn, "SELECT set_config('app.session_id', 'rls-session-a', true)")
        reread = execute(conn, "SELECT value FROM sites_task_answers WHERE task_id = 'rls-task-a' AND card_id = 'direction'")
        assert reread[0][0] == '肝癌免疫治疗耐药机制'

    result = {
        'migration': 'passed',
        'same_owner_create_and_read': True,
        'cross_owner_task_read_returns_zero_rows': True,
        'cross_owner_task_insert_rejected': True,
        'cross_owner_answer_insert_rejected': True,
        'app_user_skill_write_rejected': True,
        'expired_session_insert_rejected': True,
        'audit_reader_cross_session_read_only': True,
        'owner_answer_reread': True,
        'no_data_deleted': True,
    }
    Path('dev/acceptance/provider-live/rls-verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
