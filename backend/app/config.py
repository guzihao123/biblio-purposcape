from functools import lru_cache
import os
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEVELOPMENT_SESSION_SECRET = secrets.token_urlsafe(32)
_DEVELOPMENT_ADMIN_TOKEN = secrets.token_urlsafe(32)


class Settings(BaseSettings):
    app_env: str = 'development'
    task_store_authority: str = 'local'
    database_url: str = ''
    redis_url: str = 'redis://localhost:6379/0'
    frontend_dist: str = 'frontend/dist'
    artifact_root: str = './task_artifacts'
    invite_code_hash: str = ''
    session_secret: str = ''
    session_ttl_seconds: int = Field(default=604800, gt=0)
    admin_token: str = ''
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    production = (
        settings.app_env.strip().lower() in {'prod', 'production'} or
        os.environ.get('RENDER', '').strip().lower() == 'true'
    )
    if not production:
        if not settings.database_url:
            settings.database_url = 'sqlite:///./test.db'
        if not settings.session_secret:
            settings.session_secret = _DEVELOPMENT_SESSION_SECRET
        if not settings.admin_token:
            settings.admin_token = _DEVELOPMENT_ADMIN_TOKEN
        return settings

    invalid = []
    database_url = settings.database_url.strip().lower()
    if not database_url.startswith(('postgresql://', 'postgres://', 'postgresql+')):
        invalid.append('DATABASE_URL')
    if len(settings.session_secret.strip().encode('utf-8')) < 32:
        invalid.append('SESSION_SECRET')
    if len(settings.admin_token.strip().encode('utf-8')) < 32:
        invalid.append('ADMIN_TOKEN')
    if invalid:
        raise RuntimeError('Invalid production configuration: ' + ', '.join(invalid))
    return settings
