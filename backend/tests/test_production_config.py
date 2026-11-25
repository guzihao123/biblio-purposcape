import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def configure(monkeypatch, **overrides):
    values = {
        'APP_ENV': 'production',
        'RENDER': '',
        'DATABASE_URL': 'postgresql://user:password@db.example/landscape',
        'SESSION_SECRET': 's' * 32,
        'ADMIN_TOKEN': 'a' * 32,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


def test_production_accepts_external_postgres_and_fixed_secrets(monkeypatch):
    settings = configure(monkeypatch)
    assert settings.database_url.startswith('postgresql://')
    assert settings.session_secret == 's' * 32
    assert settings.admin_token == 'a' * 32


def test_production_rejects_sqlite_and_missing_secrets_with_safe_error(monkeypatch):
    with pytest.raises(RuntimeError) as caught:
        configure(
            monkeypatch,
            DATABASE_URL='sqlite:///./test.db',
            SESSION_SECRET='',
            ADMIN_TOKEN='',
        )
    message = str(caught.value)
    assert 'DATABASE_URL' in message
    assert 'SESSION_SECRET' in message
    assert 'ADMIN_TOKEN' in message
    assert 'sqlite:///./test.db' not in message
    assert 'password' not in message


def test_render_marker_enforces_production_guards(monkeypatch):
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        configure(
            monkeypatch,
            APP_ENV='development',
            RENDER='true',
            DATABASE_URL='sqlite:///./test.db',
        )


def test_production_rejects_short_secrets(monkeypatch):
    with pytest.raises(RuntimeError) as caught:
        configure(monkeypatch, SESSION_SECRET='short', ADMIN_TOKEN='also-short')
    assert 'SESSION_SECRET' in str(caught.value)
    assert 'ADMIN_TOKEN' in str(caught.value)


def test_local_development_keeps_process_local_defaults(monkeypatch):
    settings = configure(
        monkeypatch,
        APP_ENV='development',
        DATABASE_URL='',
        SESSION_SECRET='',
        ADMIN_TOKEN='',
    )
    assert settings.database_url == 'sqlite:///./test.db'
    assert len(settings.session_secret) >= 32
    assert len(settings.admin_token) >= 32


def test_standard_postgres_urls_use_the_declared_psycopg_driver():
    from app.db import normalize_database_url

    assert normalize_database_url(
        'postgresql://user:pass@host:5432/db'
    ) == 'postgresql+psycopg://user:pass@host:5432/db'
    assert normalize_database_url(
        'postgres://user:pass@host:5432/db'
    ) == 'postgresql+psycopg://user:pass@host:5432/db'
    assert normalize_database_url('sqlite:///./test.db') == 'sqlite:///./test.db'
    assert normalize_database_url(
        'postgresql+psycopg://user:pass@host/db'
    ) == 'postgresql+psycopg://user:pass@host/db'
