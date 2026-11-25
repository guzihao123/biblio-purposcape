from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_frontend_root_assets_and_spa_fallback(tmp_path, monkeypatch):
    dist = tmp_path / 'dist'
    assets = dist / 'assets'
    assets.mkdir(parents=True)
    (dist / 'index.html').write_text('<html><body>production-ui-marker</body></html>', encoding='utf-8')
    (assets / 'app.js').write_text('console.log("production-asset")', encoding='utf-8')
    monkeypatch.setattr(get_settings(), 'frontend_dist', str(dist))
    client = TestClient(app)

    for path in ('/', '/history', '/admin/skill'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'production-ui-marker' in response.text
        assert response.headers['content-type'].startswith('text/html')

    asset = client.get('/assets/app.js')
    assert asset.status_code == 200
    assert 'production-asset' in asset.text

    missing_api = client.get('/api/definitely-not-a-route')
    assert missing_api.status_code == 404
    assert missing_api.json() == {'detail': 'Not Found'}


def test_frontend_missing_index_and_traversal_return_404(tmp_path, monkeypatch):
    dist = tmp_path / 'dist'
    dist.mkdir()
    monkeypatch.setattr(get_settings(), 'frontend_dist', str(dist))
    client = TestClient(app)
    assert client.get('/').status_code == 404
    (dist / 'index.html').write_text('<html><body>safe-index</body></html>', encoding='utf-8')
    outside = tmp_path / 'secret.txt'
    outside.write_text('not-public', encoding='utf-8')
    response = client.get('/%2e%2e/secret.txt')
    assert response.status_code == 404
    assert 'not-public' not in response.text
