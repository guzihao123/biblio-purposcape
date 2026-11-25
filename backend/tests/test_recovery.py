from datetime import datetime, timedelta, timezone
import io
import logging
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, InviteSession, Task, TaskEvent, TaskJob, TaskProgress
from app.rate_limit import RateLimitRule
from app.recovery import (
    QuotaExceeded,
    enforce_quota,
    recover_interrupted_tasks,
    retry_call,
    schedule_due_retries,
)


@pytest.fixture
def session_factory():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_task(db, status='started', checkpoint=None, stage='search'):
    owner = InviteSession(id=str(uuid4()), client_ip='203.0.113.10')
    db.add(owner)
    task = Task(id=str(uuid4()), session_id=owner.id, state='searching')
    db.add(task)
    db.flush()
    answer_id = 1
    job = TaskJob(id=str(uuid4()), task_id=task.id, answer_id=answer_id, kind=stage, status=status)
    db.add(job)
    db.add(TaskProgress(
        task_id=task.id,
        stage=stage,
        message='执行中',
        input_hash='input-hash',
        checkpoint=checkpoint,
    ))
    db.commit()
    return task, job


def test_retry_call_retries_only_transient_errors_with_bounded_backoff():
    attempts = []
    sleeps = []

    def transient():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError('temporary')
        return 'ok'

    result = retry_call(transient, attempts=3, base_delay=0.1, max_delay=0.2, jitter=0, sleep=sleeps.append)
    assert result == 'ok'
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]

    calls = []
    with pytest.raises(ValueError, match='not transient'):
        retry_call(lambda: (_ for _ in ()).throw(ValueError('not transient')), attempts=3, sleep=sleeps.append)
    assert len(calls) == 0


def test_stale_checkpoint_is_settled_without_repeating_search(db, session_factory):
    task, job = make_task(db, checkpoint={'stage': 'search', 'limited_count': 50})
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    db.execute(text('UPDATE task_progress SET updated_at = :old'), {'old': old.isoformat()})
    enqueued = []
    result = recover_interrupted_tasks(
        session_factory=session_factory,
        stale_after=3600,
        now=lambda: datetime.now(timezone.utc),
        enqueue=lambda task_id, stage: enqueued.append((task_id, stage)),
    )

    assert result[0]['resumed_from'] == 'search'
    assert result[0]['duplicate_searches'] == 0
    assert enqueued == []
    db.refresh(task)
    db.refresh(job)
    assert task.state == 'dashboard_ready'
    assert task.next_card == 'adjustment'
    assert job.status == 'completed'
    assert db.query(TaskEvent).filter_by(task_id=task.id, event_type='recovered').count() == 1


def test_stale_started_without_checkpoint_requires_manual_review_instead_of_repeating_search(db, session_factory):
    task, job = make_task(db, checkpoint=None)
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    db.execute(text('UPDATE task_progress SET updated_at = :old'), {'old': old.isoformat()})
    enqueued = []
    result = recover_interrupted_tasks(
        session_factory=session_factory,
        stale_after=3600,
        now=lambda: datetime.now(timezone.utc),
        enqueue=lambda task_id, stage: enqueued.append((task_id, stage)),
    )

    assert result[0]['action'] == 'manual_review'
    assert result[0]['duplicate_searches'] == 0
    assert enqueued == []
    db.refresh(task)
    db.refresh(job)
    assert task.state == 'error'
    assert job.status == 'interrupted'


def test_fresh_started_job_is_not_touched(db, session_factory):
    task, job = make_task(db, checkpoint={'stage': 'search'})
    result = recover_interrupted_tasks(
        session_factory=session_factory,
        stale_after=3600,
        now=lambda: datetime.now(timezone.utc),
        enqueue=lambda task_id, stage: (_ for _ in ()).throw(AssertionError('must not enqueue')),
    )

    assert result == []
    db.refresh(job)
    assert job.status == 'started'


def test_due_rate_limit_retry_is_requeued_once_with_delay_and_attempt_cap(db, session_factory):
    task, job = make_task(db, status='failed', checkpoint=None)
    task.state = 'error'
    db.add(TaskEvent(
        task_id=task.id,
        event_type='rate_limited',
        payload={'retry_after': 60, 'message': '请求过于频繁'},
    ))
    old = datetime.now(timezone.utc) - timedelta(seconds=90)
    db.execute(text('UPDATE task_progress SET updated_at = :old'), {'old': old.isoformat()})
    db.commit()
    enqueued = []
    result = schedule_due_retries(
        session_factory=session_factory,
        now=lambda: datetime.now(timezone.utc),
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
    )

    assert result[0]['action'] == 'requeued'
    db.refresh(job)
    assert job.status == 'queued'
    assert enqueued == [(task.id, 'search', 0)]

    second = schedule_due_retries(
        session_factory=session_factory,
        now=lambda: datetime.now(timezone.utc),
        enqueue=lambda task_id, stage, delay: enqueued.append((task_id, stage, delay)),
    )
    assert second == []


def test_quota_enforcement_is_isolated_by_session(isolated_rate_limiter):
    isolated_rate_limiter.rules = {
        'task_create': {'session': RateLimitRule(1, 3600)},
    }
    enforce_quota('task_create', session_id='first', source_ip='203.0.113.10', idempotency_key='a', limiter=isolated_rate_limiter)
    with pytest.raises(QuotaExceeded):
        enforce_quota('task_create', session_id='first', source_ip='203.0.113.10', idempotency_key='b', limiter=isolated_rate_limiter)
    enforce_quota('task_create', session_id='second', source_ip='203.0.113.10', idempotency_key='c', limiter=isolated_rate_limiter)


def test_sensitive_diagnostic_redaction_covers_all_worker_failure_categories():
    from app.recovery import redact_sensitive_text

    environment_value = 'fake-environment-value-a90e'
    private_values = [
        'fake-token-redaction-7f3a',
        'fake-password-redaction-91b2',
        'fake-secret-redaction-c814',
        'fake-provider-body-private-record-52de',
        'fake-provider-private-note-18bd',
        'fake_private_customers',
        'fake-url-password-63ad',
        '/Users/fake-worker/private/fake-task.db',
        r'C:\fake-server\private\fake-task.db',
        environment_value,
    ]
    raw = (
        'RuntimeError: OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE\n'
        'token=fake-token-redaction-7f3a; password="fake-password-redaction-91b2"; '
        'secret: fake-secret-redaction-c814\n'
        'Provider response body={\n'
        '  "private_record": "fake-provider-body-private-record-52de",\n'
        '  "private_note": "fake-provider-private-note-18bd"\n'
        '}\n'
        'SQL: SELECT * FROM fake_private_customers;\n'
        'redis://fake-user:fake-url-password-63ad@private.internal:6379/0\n'
        '/Users/fake-worker/private/fake-task.db; '
        r'C:\fake-server\private\fake-task.db' + '\n'
        f'env={environment_value}'
    )

    protected = redact_sensitive_text(
        raw,
        environ={'WORKER_REDACTION_TEST_SECRET': environment_value},
    )

    for private_value in private_values:
        assert private_value not in protected
    assert 'SELECT' not in protected
    assert 'private_record' not in protected
    assert '/Users/' not in protected
    assert r'C:\fake-server' not in protected
    assert '[REDACTED_PROVIDER_BODY]' in protected
    assert '[REDACTED_SQL]' in protected
    assert '[REDACTED_CREDENTIALS]@' in protected
    assert '[REDACTED_PATH]' in protected
    assert '[REDACTED_ENV]' in protected
    assert 'RuntimeError' in protected
    assert 'OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE' in protected


def test_uvicorn_access_and_exception_logs_redact_artifact_requests(caplog, capfd):
    from uvicorn.logging import AccessFormatter

    from app.recovery import install_worker_log_redaction

    install_worker_log_redaction()
    task_id = str(uuid4())
    signature = 'fake-artifact-signature-91d47c'
    target = (
        f'/api/tasks/{task_id}/artifacts/report.docx'
        f'?signature={signature}&expires=1799999999'
    )
    access = logging.getLogger('uvicorn.access')
    error = logging.getLogger('uvicorn.error')
    access_stream = io.StringIO()
    access_handler = logging.StreamHandler(access_stream)
    access_handler.setFormatter(AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    ))
    previous = [(logger, logger.level) for logger in (access, error)]
    access.addHandler(access_handler)
    error.addHandler(caplog.handler)
    for logger, _ in previous:
        logger.setLevel(logging.INFO)
    try:
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            '127.0.0.1:12345', 'GET', target, '1.1', 200,
        )
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            '127.0.0.1:12345', 'GET', '/api/health', '1.1', 200,
        )
        try:
            raise RuntimeError(
                f'Could not read /Users/fake-worker/private/{task_id}/report.docx'
            )
        except RuntimeError:
            error.exception('Unhandled artifact download exception')
    finally:
        access.removeHandler(access_handler)
        error.removeHandler(caplog.handler)
        for logger, level in previous:
            logger.setLevel(level)

    rendered = access_stream.getvalue() + caplog.text
    handler_errors = capfd.readouterr().err
    assert 'Logging error' not in handler_errors
    assert signature not in rendered + handler_errors
    assert task_id not in rendered + handler_errors
    assert 'report.docx' not in rendered + handler_errors
    assert '/Users/' not in rendered + handler_errors
    assert '[REDACTED_PATH]' in rendered
    assert '[REDACTED]' in rendered
    assert 'GET /api/health HTTP/1.1' in access_stream.getvalue()


def test_env_redaction_keeps_configuration_values_and_names_intact():
    """Only credential-ish env values are replaced; diagnostics survive verbatim."""
    from app.recovery import redact_sensitive_text

    environ = {
        'PAGER': 'cat',
        'LOGNAME': 'root',
        'SHLVL': '1',
        'CODEBUDDY_API_KEY_HELPER_DISABLED': '1',
        'MAX_TOKENS': '4096',
        'GALILEO_ENABLE': 'true',
        'BROWSER_USE_CHROMIUM_SANDBOX': 'false',
        'WORKER_SHARED_SECRET': 'fake-worker-secret-4f21',
    }
    raw = (
        '127.0.0.1:48213 - "GET /api/health HTTP/1.1" 200\n'
        'catalog category root line 1522 max_tokens=4096 debug=true\n'
        'WORKER_SHARED_SECRET=fake-worker-secret-4f21 PAGER=cat'
    )

    protected = redact_sensitive_text(raw, environ=environ)

    assert '127.0.0.1' in protected
    assert 'HTTP/1.1' in protected
    assert 'line 1522' in protected
    assert 'max_tokens=4096' in protected
    assert 'catalog category root' in protected
    assert 'WORKER_SHARED_SECRET=' in protected
    assert 'PAGER=cat' in protected
    assert 'fake-worker-secret-4f21' not in protected
    assert '[REDACTED_ENV]' in protected


def test_env_redaction_uses_value_shape_for_unlabelled_credentials():
    from app.recovery import redact_sensitive_text

    token = 'sk-live-3c9d7a1b4e5f60718293'
    environ = {'SOME_PLAIN_SETTING': token}
    message = f'upstream returned {token} after 2 retries'

    protected = redact_sensitive_text(message, environ=environ)

    assert token not in protected
    assert '[REDACTED_ENV]' in protected
    assert 'upstream returned' in protected
    assert 'after 2 retries' in protected


@pytest.mark.parametrize(
    ('name', 'value'),
    [
        ('CODEBUDDY_API_KEY_HELPER_DISABLED', '1'),
        ('SECRET_STORE_ENABLED', '0'),
        ('MAX_TOKENS', '4096'),
        ('TOKEN_BUDGET', '30000'),
        ('GALILEO_ENABLE', 'true'),
        ('BROWSER_USE_CHROMIUM_SANDBOX', 'false'),
        ('PAGER', 'cat'),
        ('LOGNAME', 'root'),
        ('APP_ENV', 'development'),
        ('PYTHONIOENCODING', 'utf-8'),
    ],
)
def test_flag_numeric_and_short_word_values_are_never_redacted(name, value):
    """Settings that merely live next to a secret-like name must survive verbatim."""
    from app.recovery import redact_sensitive_text

    raw = 'pid 12345 status {} pid 12345'.format(value)

    protected = redact_sensitive_text(raw, environ={name: value})

    assert protected == raw
    assert '[REDACTED_ENV]' not in protected


@pytest.mark.parametrize(
    'token',
    [
        'sk-' + '3c9d7a1b4e5f60718293',
        'sk_' + 'live_4eC39HqLyjWDarjtT1zdp7dc',
        'ghp_' + '16C7e42F292c6912E7710c838347Ae178B4a',
        'github_pat_' + '11ABCDEFG0abcdefghijkl_abcdefghijklmnopqrstuvwxyz0123456789AB',
        'xoxb-' + '123456789012-abcdefghijklmnop',
        'AKIA' + 'IOSFODNN7EXAMPLE',
        'AIza' + 'SyD-1234567890abcdefghijklmnopqrstu',
        'eyJ' + 'hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U',
    ],
)
def test_known_credential_shapes_are_redacted_under_an_innocuous_name(token):
    """A value in a known key format is redacted even when the name says nothing."""
    from app.recovery import redact_sensitive_text

    raw = 'upstream rejected {} after 3 attempts'.format(token)

    protected = redact_sensitive_text(raw, environ={'SOME_PLAIN_SETTING': token})

    assert token not in protected
    assert '[REDACTED_ENV]' in protected
    assert protected.startswith('upstream rejected ')
    assert protected.endswith(' after 3 attempts')


@pytest.mark.parametrize(
    ('name', 'value'),
    [
        ('QWEN_API_KEY', 'fake-qwen-key-7c1d'),
        ('SESSION_SECRET', 'fake-session-secret-2b8e'),
        ('ADMIN_TOKEN', 'fake-admin-token-93af'),
        ('WORKER_SHARED_SECRET', 'fake-worker-secret-4f21'),
        ('OPENAI_KEY', 'fakeOpenAiKey9f3aC7d21b'),
    ],
)
def test_credential_named_variables_with_real_values_are_redacted(name, value):
    from app.recovery import redact_sensitive_text

    protected = redact_sensitive_text(
        'boot with {}={}'.format(name, value),
        environ={name: value},
    )

    assert value not in protected
    assert name + '=' in protected


def test_worker_log_filter_drops_the_secret_before_any_handler_formats_it(monkeypatch):
    """The end-to-end guarantee: a formatted worker record never carries the key."""
    from app.recovery import WorkerLogRedactionFilter

    secret = 'fake-worker-shared-secret-5d18'
    monkeypatch.setenv('WORKER_SHARED_SECRET', secret)
    record = logging.LogRecord(
        'rq.worker',
        logging.ERROR,
        __file__,
        1522,
        'stage failed: secret in env=%s and header api_key=%s',
        (secret, 'sk-live-8f3a91c2d4b5e6071a2b'),
        None,
    )

    assert WorkerLogRedactionFilter().filter(record) is True

    rendered = record.getMessage()
    assert secret not in rendered
    assert 'sk-live-8f3a91c2d4b5e6071a2b' not in rendered
    assert 'stage failed' in rendered
    assert 'in env=' in rendered
    assert 'header api_key=' in rendered
    assert record.args == ()
    assert record.exc_info is None
