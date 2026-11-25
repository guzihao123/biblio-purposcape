from types import SimpleNamespace

from fastapi.testclient import TestClient
from app.main import app
from app.queueing import QueueAdapter, worker_status


def test_health_reports_service_and_database(monkeypatch):
    monkeypatch.setattr('app.queueing.get_settings', lambda: SimpleNamespace(redis_url=''))
    response = TestClient(app).get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'database': 'ok', 'worker': 'not_configured'}


def test_web_starts_with_redis_not_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv('REDIS_URL', '')
    get_settings.cache_clear()
    adapter = QueueAdapter()
    assert adapter.queue is None
    assert worker_status() == 'not_configured'
    get_settings.cache_clear()
