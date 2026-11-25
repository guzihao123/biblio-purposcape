from __future__ import annotations

import json
import os
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg


HERE = Path(__file__).resolve().parent
REQUIRED_ENV = ('DATABASE_URL', 'APP_USER_PASSWORD', 'APP_ADMIN_PASSWORD', 'AUDIT_READER_PASSWORD')
TABLES = (
    'sites_anonymous_sessions', 'sites_skill_versions', 'sites_tasks',
    'sites_task_answers', 'sites_task_artifacts', 'sites_task_quota_windows',
)


def require_env():
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError('missing env: ' + ', '.join(missing))


def run_id():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f'{stamp}-{suffix}'


def parameters(role):
    values = psycopg.conninfo.conninfo_to_dict(os.environ['DATABASE_URL'])
    original_user = values.get('user', '')
    if role == 'fixture_admin':
        values['connect_timeout'] = 10
        values['prepare_threshold'] = None
        return values
    values['user'] = role
    if '.' in original_user:
        values['user'] = f'{role}.{original_user.split(".", 1)[1]}'
    values['password'] = os.environ[f'{role.upper()}_PASSWORD']
    values['connect_timeout'] = 10
    values['prepare_threshold'] = None
    return values


def connect(role):
    return psycopg.connect(**parameters(role))


def execute(connection, statement, parameters=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        return cursor.fetchall() if cursor.description else []


def bind(connection, session_id):
    execute(connection, "SELECT set_config('app.session_id', %s, true)", (session_id,))


def expect_denied(connection, statement, parameters=()):
    try:
        with connection.transaction():
            execute(connection, statement, parameters)
    except psycopg.errors.InsufficientPrivilege as error:
        assert error.sqlstate == '42501'
        return {'denied': True, 'sqlstate': error.sqlstate}
    raise AssertionError('write unexpectedly succeeded')


def scalar(connection, statement, parameters=()):
    rows = execute(connection, statement, parameters)
    return rows[0][0] if rows else None


class Validation:
    def __init__(self, prefix):
        self.prefix = prefix
        self.skill = f'{prefix}-skill'
        self.cases = {}

    def sid(self, number):
        return f'{self.prefix}-s{number:02d}'

    def tid(self, number):
        return f'{self.prefix}-t{number:02d}'

    def record(self, name, status, **details):
        self.cases[name] = {'status': status, **details}

    def seed(self):
        with connect('fixture_admin') as admin:
            existing = execute(admin, "SELECT id FROM sites_skill_versions WHERE state = 'published' LIMIT 1")
            if existing:
                self.skill = existing[0][0]
            else:
                version = int(datetime.now(timezone.utc).timestamp() * 1000) % 2_000_000_000
                execute(admin, """
                    INSERT INTO sites_skill_versions (
                        id, version, parent_id, state, content, content_hash,
                        regression_report, created_at, published_at
                    ) VALUES (%s, %s, NULL, 'published', '{}', %s, '{"passed":true}', now(), now())
                """, (self.skill, version, 'a' * 64))
            for number in (1, 2, 3, 4, 5, 7, 9):
                execute(admin, """
                    INSERT INTO sites_anonymous_sessions (
                        id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at
                    ) VALUES (%s, '203.0.113.10', 'incremental-rls', now(), now(), now() + interval '2 days', NULL)
                """, (self.sid(number),))
            for number, owner in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (7, 7)):
                execute(admin, """
                    INSERT INTO sites_tasks (
                        id, session_id, skill_version_id, idempotency_key, state, next_card,
                        revision, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'collecting_mode', 'direction', 1, now(), now())
                """, (self.tid(number), self.sid(owner), self.skill, f'{self.prefix}-key-{number}'))
            execute(admin, """
                INSERT INTO sites_task_answers (task_id, card_id, value, created_at, updated_at)
                VALUES (%s, 'direction', '"seed"'::jsonb, now(), now())
            """, (self.tid(4),))
            execute(admin, """
                INSERT INTO sites_task_answers (task_id, card_id, value, created_at, updated_at)
                VALUES (%s, 'direction', '"seed"'::jsonb, now(), now())
            """, (self.tid(5),))
            for number in (4, 5):
                execute(admin, """
                    INSERT INTO sites_task_artifacts (
                        task_id, name, object_path, size_bytes, content_type, metadata
                    ) VALUES (%s, 'seed.txt', %s, 4, 'text/plain', '{}')
                """, (self.tid(number), f'artifacts/{self.tid(number)}/seed.txt'))
                execute(admin, """
                    INSERT INTO sites_task_quota_windows (session_id, window_start, used)
                    VALUES (%s, now(), 1)
                """, (self.sid(number),))
                execute(admin, """
                    INSERT INTO sites_task_jobs (id, task_id, stage, input_hash, status, task_revision)
                    VALUES (%s, %s, 'search', %s, 'queued', 1)
                """, (f'{self.prefix}-job-{number}', self.tid(number), 'f' * 64))
                execute(admin, """
                    INSERT INTO sites_task_progress (task_id, job_id, message)
                    VALUES (%s, %s, 'queued')
                """, (self.tid(number), f'{self.prefix}-job-{number}'))
                execute(admin, """
                    INSERT INTO sites_task_events (task_id, job_id, event_type, event_key, payload)
                    VALUES (%s, %s, 'queued', %s, '{}'::jsonb)
                """, (self.tid(number), f'{self.prefix}-job-{number}', f'{self.prefix}-event-{number}'))

    def same_owner(self):
        with connect('app_user') as conn:
            with conn.transaction():
                bind(conn, self.sid(1))
                execute(conn, """
                    INSERT INTO sites_task_artifacts (
                        task_id, name, object_path, size_bytes, content_type,
                        checksum_sha256, metadata, created_at, updated_at
                    ) VALUES (%s, 'report.docx', %s, 10, 'application/octet-stream', %s, '{}', now(), now())
                """, (self.tid(1), f'artifacts/{self.tid(1)}/report.docx', 'b' * 64))
                execute(conn, """
                    UPDATE sites_task_artifacts SET size_bytes = 25, updated_at = now()
                    WHERE task_id = %s AND name = 'report.docx'
                """, (self.tid(1),))
                size = scalar(conn, "SELECT size_bytes FROM sites_task_artifacts WHERE task_id = %s AND name = 'report.docx'", (self.tid(1),))
                assert size == 25
                used = scalar(conn, """
                    INSERT INTO sites_task_quota_windows (session_id, window_start, used, created_at, updated_at)
                    SELECT %s, now(), 1, now(), now()
                    ON CONFLICT (session_id, window_start) DO UPDATE SET
                      used = sites_task_quota_windows.used + 1, updated_at = now()
                    WHERE sites_task_quota_windows.used + 1 <= 5
                    RETURNING used
                """, (self.sid(1),))
                assert used == 1
                execute(conn, """
                    INSERT INTO sites_task_jobs (id, task_id, stage, input_hash, status, task_revision)
                    VALUES (%s, %s, 'search', %s, 'queued', 1)
                """, (f'{self.prefix}-job-1', self.tid(1), 'c' * 64))
                execute(conn, """
                    INSERT INTO sites_task_progress (task_id, job_id, message)
                    VALUES (%s, %s, 'queued')
                """, (self.tid(1), f'{self.prefix}-job-1'))
                execute(conn, """
                    INSERT INTO sites_task_events (task_id, job_id, event_type, event_key, payload)
                    VALUES (%s, %s, 'queued', %s, '{}'::jsonb)
                """, (self.tid(1), f'{self.prefix}-job-1', f'{self.prefix}-queued-1'))
                assert scalar(conn, 'SELECT count(*) FROM sites_task_jobs WHERE id = %s', (f'{self.prefix}-job-1',)) == 1
                assert scalar(conn, 'SELECT count(*) FROM sites_task_progress WHERE task_id = %s', (self.tid(1),)) == 1
                assert scalar(conn, 'SELECT count(*) FROM sites_task_events WHERE job_id = %s', (f'{self.prefix}-job-1',)) == 1
        self.record('INC-01_same_owner_artifacts_quota', 'passed', artifacts_update=True, quota_used=1, stage_rows=True)

    def cross_owner(self):
        denied = 0
        with connect('app_user') as conn:
            bind(conn, self.sid(2))
            for table, key in (
                ('sites_tasks', f"id = '{self.tid(1)}'"),
                ('sites_task_answers', f"task_id = '{self.tid(1)}'"),
                ('sites_task_artifacts', f"task_id = '{self.tid(1)}'"),
                ('sites_task_quota_windows', f"session_id = '{self.sid(1)}'"),
                ('sites_task_jobs', f"task_id = '{self.tid(1)}'"),
                ('sites_task_progress', f"task_id = '{self.tid(1)}'"),
                ('sites_task_events', f"task_id = '{self.tid(1)}'"),
            ):
                count = scalar(conn, f'SELECT count(*) FROM {table} WHERE {key}')
                assert count == 0, (table, count)
                timestamp_column = 'created_at' if table == 'sites_task_events' else 'updated_at'
                updated = execute(conn, f'UPDATE {table} SET {timestamp_column} = now() WHERE {key} RETURNING 1')
                assert updated == []
                deleted = execute(conn, f'DELETE FROM {table} WHERE {key} RETURNING 1')
                assert deleted == []
                denied += 3
            expect_denied(conn, """
                INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
                VALUES (%s, %s, %s, 'cross-insert', 'collecting_mode', 'direction')
            """, (f'{self.prefix}-cross', self.sid(1), self.skill))
            denied += 1
        self.record('INC-02_cross_owner_matrix', 'passed', rejected_operations=denied)

    def audit_write_denial(self):
        denied = 0
        with connect('audit_reader') as conn:
            statements = [
                ("INSERT INTO sites_anonymous_sessions (id) VALUES (%s)", (f'{self.prefix}-audit',)),
                ("UPDATE sites_anonymous_sessions SET user_agent = 'x' WHERE id = %s", (self.sid(1),)),
                ("DELETE FROM sites_anonymous_sessions WHERE id = %s", (self.sid(1),)),
                ("INSERT INTO sites_skill_versions (id, version, state, content, content_hash) VALUES (%s, 999999, 'draft', '{}', %s)", (f'{self.prefix}-audit-skill', 'c' * 64)),
                ("UPDATE sites_skill_versions SET state = 'archived' WHERE id = %s", (self.skill,)),
                ("DELETE FROM sites_skill_versions WHERE id = %s", (self.skill,)),
                ("INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state) VALUES (%s, %s, %s, 'audit', 'error')", (f'{self.prefix}-audit-task', self.sid(1), self.skill)),
                ("UPDATE sites_tasks SET state = 'error' WHERE id = %s", (self.tid(1),)),
                ("DELETE FROM sites_tasks WHERE id = %s", (self.tid(1),)),
                ("INSERT INTO sites_task_answers (task_id, card_id, value) VALUES (%s, 'mode', '{}')", (self.tid(1),)),
                ("UPDATE sites_task_answers SET value = '{}'::jsonb WHERE task_id = %s", (self.tid(1),)),
                ("DELETE FROM sites_task_answers WHERE task_id = %s", (self.tid(1),)),
                ("INSERT INTO sites_task_artifacts (task_id, name, object_path, size_bytes, content_type) VALUES (%s, 'x', 'x', 1, 'text/plain')", (self.tid(1),)),
                ("UPDATE sites_task_artifacts SET size_bytes = 2 WHERE task_id = %s", (self.tid(1),)),
                ("DELETE FROM sites_task_artifacts WHERE task_id = %s", (self.tid(1),)),
                ("INSERT INTO sites_task_quota_windows (session_id, window_start, used) VALUES (%s, now(), 1)", (self.sid(1),)),
                ("UPDATE sites_task_quota_windows SET used = 2 WHERE session_id = %s", (self.sid(1),)),
                ("DELETE FROM sites_task_quota_windows WHERE session_id = %s", (self.sid(1),)),
                ("INSERT INTO sites_task_jobs (id, task_id, stage, input_hash, status, task_revision) VALUES (%s, %s, 'search', %s, 'queued', 1)", (f'{self.prefix}-audit-job', self.tid(1), 'd' * 64)),
                ("UPDATE sites_task_jobs SET status = 'failed' WHERE id = %s", (f'{self.prefix}-job-1',)),
                ("DELETE FROM sites_task_jobs WHERE id = %s", (f'{self.prefix}-job-1',)),
                ("INSERT INTO sites_task_progress (task_id, job_id) VALUES (%s, %s)", (self.tid(1), f'{self.prefix}-job-1')),
                ("UPDATE sites_task_progress SET message = 'x' WHERE task_id = %s", (self.tid(1),)),
                ("DELETE FROM sites_task_progress WHERE task_id = %s", (self.tid(1),)),
                ("INSERT INTO sites_task_events (task_id, job_id, event_type, event_key, payload) VALUES (%s, %s, 'failed', %s, '{}')", (self.tid(1), f'{self.prefix}-job-1', f'{self.prefix}-audit-event')),
                ("UPDATE sites_task_events SET payload = '{}'::jsonb WHERE job_id = %s", (f'{self.prefix}-job-1',)),
                ("DELETE FROM sites_task_events WHERE job_id = %s", (f'{self.prefix}-job-1',)),
            ]
            for statement, values in statements:
                expect_denied(conn, statement, values)
                denied += 1
            assert scalar(conn, 'SELECT count(*) FROM sites_tasks') >= 1
        self.record('INC-03_audit_write_denial', 'passed', denied_writes=denied)

    def revoked_expired(self):
        with connect('fixture_admin') as admin:
            execute(admin, 'UPDATE sites_anonymous_sessions SET revoked_at = now() WHERE id = %s', (self.sid(4),))
            execute(admin, 'UPDATE sites_anonymous_sessions SET expires_at = now() - interval \'1 hour\' WHERE id = %s', (self.sid(5),))
        for number in (4, 5):
            with connect('app_user') as conn:
                bind(conn, self.sid(number))
                for table in (
                    'sites_tasks', 'sites_task_answers', 'sites_task_artifacts', 'sites_task_quota_windows',
                    'sites_task_jobs', 'sites_task_progress', 'sites_task_events',
                ):
                    count = scalar(conn, f'SELECT count(*) FROM {table}')
                    assert count == 0, (number, table, count)
                expect_denied(conn, """
                    INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
                    VALUES (%s, %s, %s, %s, 'collecting_mode', 'direction')
                """, (f'{self.prefix}-blocked-{number}', self.sid(number), self.skill, f'{self.prefix}-blocked-key-{number}'))
                expect_denied(conn, """
                    INSERT INTO sites_task_answers (task_id, card_id, value)
                    VALUES (%s, 'mode', '{}'::jsonb)
                """, (self.tid(number),))
                expect_denied(conn, """
                    INSERT INTO sites_task_quota_windows (session_id, window_start, used)
                    VALUES (%s, now(), 1)
                """, (self.sid(number),))
                expect_denied(conn, """
                    INSERT INTO sites_task_jobs (id, task_id, stage, input_hash, status, task_revision)
                    VALUES (%s, %s, 'search', %s, 'queued', 1)
                """, (f'{self.prefix}-blocked-job-{number}', self.tid(number), 'e' * 64))
        self.record('INC-04_revoked_expired_read_write', 'passed', sessions=[4, 5], reads_zero=True, writes_denied=True)

    def session_dual_path(self):
        with connect('app_user') as conn:
            with conn.transaction():
                execute(conn, 'INSERT INTO sites_anonymous_sessions (id, expires_at) VALUES (%s, now() + interval \'1 day\')', (self.sid(6),))
            bound_id = f'{self.prefix}-bound'
            with conn.transaction():
                bind(conn, bound_id)
                execute(conn, 'INSERT INTO sites_anonymous_sessions (id, expires_at) VALUES (%s, now() + interval \'1 day\')', (bound_id,))
            bind(conn, self.sid(6))
            expect_denied(
                conn,
                'INSERT INTO sites_anonymous_sessions (id, expires_at) VALUES (%s, now() + interval \'1 day\')',
                (f'{self.prefix}-different',),
            )
        self.record('INC-05_session_create_dual_path', 'passed', null_guc_create=True, same_id_create=True, different_id_rejected=True)

    def guc_reuse(self):
        with connect('app_user') as conn:
            with conn.transaction():
                bind(conn, self.sid(1))
                assert scalar(conn, 'SELECT count(*) FROM sites_tasks WHERE id = %s', (self.tid(1),)) == 1
            with conn.transaction():
                bind(conn, self.sid(2))
                assert scalar(conn, 'SELECT count(*) FROM sites_tasks WHERE id = %s', (self.tid(1),)) == 0
                assert scalar(conn, 'SELECT count(*) FROM sites_tasks WHERE id = %s', (self.tid(2),)) == 1
            with conn.transaction():
                assert scalar(conn, 'SELECT count(*) FROM sites_tasks WHERE id = ANY(%s)', ([self.tid(1), self.tid(2)],)) == 0
        self.record('INC-06_transaction_guc_reset', 'passed', third_transaction_unbound_reads_zero=True)

    def revision_and_rollback(self):
        winners = []
        barrier = threading.Barrier(8)

        def compete(index):
            with connect('app_user') as conn:
                barrier.wait(timeout=15)
                with conn.transaction():
                    bind(conn, self.sid(3))
                    rows = execute(conn, """
                        UPDATE sites_tasks SET state = 'searching', revision = revision + 1, updated_at = now()
                        WHERE id = %s AND session_id = %s AND revision = 1
                        RETURNING revision
                    """, (self.tid(3), self.sid(3)))
                    winners.append(rows)

        threads = [threading.Thread(target=compete, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads)
        assert sum(1 for rows in winners if rows) == 1
        with connect('audit_reader') as audit:
            assert scalar(audit, 'SELECT revision FROM sites_tasks WHERE id = %s', (self.tid(3),)) == 2
            before = execute(audit, 'SELECT revision, updated_at FROM sites_tasks WHERE id = %s', (self.tid(7),))[0]
        with connect('app_user') as conn:
            bind(conn, self.sid(7))
            try:
                with conn.transaction():
                    execute(conn, """
                        UPDATE sites_tasks SET state = 'searching', revision = revision + 1, updated_at = now()
                        WHERE id = %s AND session_id = %s AND revision = 1
                    """, (self.tid(7), self.sid(7)))
                    execute(conn, "INSERT INTO sites_task_answers (task_id, card_id, value) VALUES (%s, 'invalid-card', '{}')", (self.tid(7),))
            except psycopg.errors.CheckViolation:
                pass
        with connect('audit_reader') as audit:
            after = execute(audit, 'SELECT revision, updated_at FROM sites_tasks WHERE id = %s', (self.tid(7),))[0]
            assert after == before
            assert scalar(audit, 'SELECT count(*) FROM sites_task_answers WHERE task_id = %s', (self.tid(7),)) == 0
        self.record('INC-07_revision_cas_answer_rollback', 'passed', cas_threads=8, revision=2, rollback_exact=True)

    def idempotent_charge(self):
        barrier = threading.Barrier(8)
        outcomes = []
        errors = []

        def create(index):
            try:
                with connect('app_user') as conn:
                    barrier.wait(timeout=15)
                    with conn.transaction():
                        bind(conn, self.sid(9))
                        key = f'{self.prefix}-same-key'
                        inserted = execute(conn, """
                            INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
                            VALUES (%s, %s, %s, %s, 'collecting_mode', 'direction')
                            ON CONFLICT (session_id, idempotency_key) DO NOTHING
                            RETURNING id
                        """, (f'{self.prefix}-candidate-{index}', self.sid(9), self.skill, key))
                        if inserted:
                            charged = execute(conn, """
                                INSERT INTO sites_task_quota_windows (session_id, window_start, used, created_at, updated_at)
                                SELECT %s, now(), 1, now(), now()
                                ON CONFLICT (session_id, window_start) DO UPDATE SET
                                  used = sites_task_quota_windows.used + 1, updated_at = now()
                                WHERE sites_task_quota_windows.used + 1 <= 5
                                RETURNING used
                            """, (self.sid(9),))
                            assert charged
                        task = execute(conn, 'SELECT id FROM sites_tasks WHERE session_id = %s AND idempotency_key = %s', (self.sid(9), key))
                        assert task
                        outcomes.append(task[0][0])
            except Exception as error:
                errors.append(type(error).__name__)

        threads = [threading.Thread(target=create, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors, errors
        assert len(set(outcomes)) == 1 and len(outcomes) == 8
        with connect('audit_reader') as audit:
            assert scalar(audit, 'SELECT count(*) FROM sites_tasks WHERE session_id = %s AND idempotency_key = %s', (self.sid(9), f'{self.prefix}-same-key')) == 1
            used = scalar(audit, 'SELECT sum(used) FROM sites_task_quota_windows WHERE session_id = %s', (self.sid(9),))
            assert used == 1, used
        self.record('INC-08_idempotent_single_charge', 'passed', concurrent_calls=8, tasks=1, quota_used=1)

    def skill_roles(self):
        with connect('app_admin') as admin:
            draft = f'{self.prefix}-draft'
            execute(admin, """
                INSERT INTO sites_skill_versions (id, version, state, content, content_hash, regression_report)
                VALUES (%s, %s, 'draft', '{}', %s, '{"passed":true}')
            """, (draft, int(datetime.now(timezone.utc).timestamp() * 1000) % 2_000_000_000, 'd' * 64))
            execute(admin, "UPDATE sites_skill_versions SET state = 'archived' WHERE id = %s", (draft,))
            assert scalar(admin, "SELECT count(*) FROM sites_skill_versions WHERE id = %s AND state = 'archived'", (draft,)) == 1
        with connect('fixture_admin') as fixture:
            execute(fixture, """
                INSERT INTO sites_tasks (id, session_id, skill_version_id, idempotency_key, state, next_card)
                VALUES (%s, %s, %s, %s, 'collecting_mode', 'direction')
            """, (f'{self.prefix}-skill-task', self.sid(1), draft, f'{self.prefix}-skill-task-key'))
        with connect('app_user') as user:
            states = [row[0] for row in execute(user, 'SELECT DISTINCT state FROM sites_skill_versions')]
            assert states == ['published'], states
            expect_denied(user, "INSERT INTO sites_skill_versions (id, version, state, content, content_hash) VALUES (%s, 999999998, 'draft', '{}', %s)", (f'{self.prefix}-user-skill', 'e' * 64))
            with user.transaction():
                bind(user, self.sid(1))
                assert scalar(user, 'SELECT count(*) FROM sites_skill_versions WHERE id = %s AND state = \'archived\'', (draft,)) == 1
            with user.transaction():
                bind(user, self.sid(2))
                assert scalar(user, 'SELECT count(*) FROM sites_skill_versions WHERE id = %s AND state = \'archived\'', (draft,)) == 0
        with connect('audit_reader') as audit:
            published = scalar(audit, "SELECT count(*) FROM sites_skill_versions WHERE state = 'published'")
        if published:
            self.record('INC-09_skill_publish_concurrency', 'blocked', reason='existing published row preserved; no non-run data modified')
        else:
            self.record('INC-09_skill_publish_concurrency', 'not_implemented', reason='safe concurrency fixture requires a separate empty published namespace')
        self.record('INC-10_skill_role_visibility', 'passed', admin_draft_archive=True, user_only_published=True, user_write_denied=True, task_linked_archived_owner_only=True)

    def run(self):
        self.seed()
        for name, method in (
            ('same_owner', self.same_owner),
            ('cross_owner', self.cross_owner),
            ('audit_write_denial', self.audit_write_denial),
            ('revoked_expired', self.revoked_expired),
            ('session_dual_path', self.session_dual_path),
            ('guc_reuse', self.guc_reuse),
            ('revision_and_rollback', self.revision_and_rollback),
            ('idempotent_charge', self.idempotent_charge),
            ('skill_roles', self.skill_roles),
        ):
            try:
                method()
            except Exception as error:
                self.record(name, 'failed', error_type=type(error).__name__, sqlstate=getattr(error, 'sqlstate', None))
        return self.cases


def main():
    require_env()
    prefix = run_id()
    validation = Validation(prefix)
    cases = validation.run()
    counts = {}
    for case in cases.values():
        counts[case['status']] = counts.get(case['status'], 0) + 1
    report = {
        'run_id': prefix,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'cases': cases,
        'summary': counts,
        'data_deleted': False,
        'non_run_data_modified': False,
        'unverified_boundaries': [
            'The generated _qoder/database.mjs adapter was not present; worker-side GUC wiring remains unverified.',
            'Existing published Skill rows were preserved; no publish concurrency claim is made when the namespace is occupied.',
            'No Qoder Storage bytes, cloud deployment, production migration, or paid model calls were exercised.',
        ],
    }
    path = HERE / f'rls-verification-{prefix}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': path.name, 'summary': counts, 'data_deleted': False}))


if __name__ == '__main__':
    main()
