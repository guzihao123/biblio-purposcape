import hashlib
import json
from pathlib import Path

import pytest

from app.sites_store import SitesStorageClient


ROOT = Path(__file__).resolve().parents[2]


def read(name):
    return (ROOT / name).read_text(encoding='utf-8')


def test_render_has_separate_web_and_worker_services():
    config = read('render.yaml')
    assert 'name: biblio-purposcape' in config
    assert 'landscape-worker' in config
    assert 'type: web' in config
    assert 'type: worker' in config
    assert 'dockerCommand: python worker.py' in config
    assert 'python -m rq worker' not in config
    assert 'landscape-redis' in config


def test_worker_entrypoint_registers_stages_before_starting_rq():
    source = read('worker.py')
    assert 'from redis import Redis' in source
    assert 'from app.queueing import QUEUE_NAME, ProtectedWorker' in source
    assert 'register_stage_services()' in source
    assert 'ProtectedWorker([QUEUE_NAME], connection=connection).work()' in source


def test_dockerfile_builds_frontend_and_installs_linux_runtime_dependencies():
    dockerfile = read('Dockerfile')
    assert 'node:' in dockerfile
    assert 'npm run build' in dockerfile
    assert 'python:' in dockerfile
    for package in (
        'fontconfig', 'fonts-noto-cjk', 'libgl1', 'libglib2.0-0',
        'libcairo2', 'libgomp1',
    ):
        assert package in dockerfile
    assert 'uvicorn' in dockerfile
    assert 'PIP_DEFAULT_TIMEOUT=60' in dockerfile
    assert 'PIP_RETRIES=5' in dockerfile
    bootstrap = 'RUN pip install --no-cache-dir --upgrade pip setuptools wheel'
    project_install = 'RUN pip install --no-cache-dir .'
    assert bootstrap in dockerfile
    assert project_install in dockerfile
    assert dockerfile.index(bootstrap) < dockerfile.index(project_install)
    assert 'ARG VITE_API_BASE_URL=/api' in dockerfile
    assert 'COPY --from=frontend /app/frontend/dist ./frontend/dist' in dockerfile


def test_render_marks_web_and_worker_as_production():
    blueprint = read('render.yaml')
    assert blueprint.count('key: APP_ENV') == 2
    assert blueprint.count('value: production') == 2


def test_dockerfile_does_not_copy_local_env_or_databases_into_build_stages():
    dockerfile = read('Dockerfile')
    assert 'COPY frontend/ ./' not in dockerfile
    assert 'COPY . ' not in dockerfile
    assert 'COPY .env' not in dockerfile
    assert 'COPY test.db' not in dockerfile
    assert 'COPY frontend/src ./src' in dockerfile
    assert 'COPY frontend/tests ./tests' in dockerfile


def test_dockerignore_excludes_local_secrets_state_and_test_artifacts():
    ignored = read('.dockerignore')
    for pattern in (
        '.env', '.env.*', 'test.db', '*.sqlite3', '.venv/',
        'dev/', 'deliverables/', 'frontend/node_modules/',
        'frontend/test-results/', 'frontend/e2e/real-backend-results/',
    ):
        assert pattern in ignored


def test_python_project_declares_pdf_ocr_and_queue_dependencies():
    project = read('pyproject.toml')
    for dependency in (
        'pypdfium2', 'rapidocr', 'onnxruntime', 'Pillow',
        'cairosvg', 'redis', 'rq',
    ):
        assert dependency in project


def test_compose_separates_web_and_worker_and_allows_missing_local_env():
    config = read('docker-compose.yml')
    assert config.count('build: .') == 2
    assert 'command: python worker.py' in config
    assert 'image: redis:7-alpine' in config
    assert 'env_file: .env' not in config
    assert config.count('path: .env') == 2
    assert config.count('required: false') == 2
    assert config.count('REDIS_URL: redis://redis:6379/0') == 2
    assert config.count('DATABASE_URL: sqlite:////data/tasks.db') == 2
    assert config.count('landscape-data:/data') == 2


def test_env_example_documents_hybrid_services_without_real_secrets():
    text = read('.env.example')
    for name in (
        'DATABASE_URL', 'REDIS_URL', 'QWEN_API_KEY', 'QWEN_BASE_URL', 'QWEN_MODEL',
        'SESSION_SECRET', 'ADMIN_TOKEN', 'ALLOWED_ORIGINS', 'PYTHON_API_ORIGIN',
        'QODER_SITES_ORIGIN', 'WORKER_SHARED_SECRET', 'ARTIFACT_ROOT',
    ):
        assert f'{name}=' in text
    values = dict(
        line.split('=', 1)
        for line in text.splitlines()
        if line and not line.startswith('#') and '=' in line
    )
    for name in (
        'QWEN_API_KEY', 'SESSION_SECRET', 'ADMIN_TOKEN',
        'QODER_SITES_ORIGIN', 'WORKER_SHARED_SECRET',
    ):
        assert values[name] == ''
    assert 'sk-' not in text
    assert 'test-admin-token' not in text
    assert 'INVITE_CODE_HASH' not in text


def test_frontend_supports_sites_function_entry_without_hardcoding_it():
    source = read('frontend/src/api.ts')
    assert 'VITE_API_BASE_URL' in source
    assert "const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'" in source
    vite_config = read('frontend/vite.config.ts')
    assert "'/functions/v1/app'" in vite_config
    assert "'/api'" in vite_config
    assert 'VITE_API_BASE_URL=/api' in read('.env.example')
    function_source = read('sites/functions/index.ts')
    assert '/functions/v1/app' in function_source
    assert 'app(?:-[A-Za-z0-9]+)?' in function_source


def test_function_routes_complete_flow_and_preserves_binary_download_headers():
    source = read('sites/functions/index.ts')
    for route in ('/api/tasks', '/answers/', '/dashboard', '/report', '/artifacts/', '/api/admin/skill/'):
        assert route in source
    for header in ('content-disposition', 'cache-control', 'set-cookie', 'x-admin-token'):
        assert header in source
    assert 'MAX_BODY_BYTES = 50_000_000' in source
    assert 'response.body' in source


def test_python_package_discovery_is_limited_to_backend_app():
    config = read('pyproject.toml')
    assert 'requires = ["setuptools>=61", "wheel"]' in config
    assert 'package-dir = {"" = "backend"}' in config
    assert 'where = ["backend"]' in config
    assert 'include = ["app*"]' in config


def test_dev_import_map_resolves_storage_stub_without_creating_qoder_directory():
    import_map_path = ROOT / 'dev' / 'import_map.json'
    config = json.loads(import_map_path.read_text(encoding='utf-8'))
    imports = config['imports']
    source_key = '../sites/functions/_qoder/storage.mjs'
    assert imports[source_key] == './storage-stub.mjs'
    assert imports['../sites/functions/_qoder/database.mjs'] == './database-stub.mjs'
    assert (import_map_path.parent / imports[source_key]).resolve() == (
        ROOT / 'dev' / 'storage-stub.mjs'
    ).resolve()
    assert (ROOT / 'dev' / 'database-stub.mjs').is_file()
    assert (ROOT / 'dev' / 'storage-stub.mjs').is_file()
    assert not (ROOT / 'sites' / 'functions' / '_qoder').exists()
    stub = read('dev/storage-stub.mjs')
    for method in ('upload(', 'list(', 'download('):
        assert method in stub


def test_sites_storage_client_uploads_fixed_worker_paths_only():
    calls = []

    def transport(url, options):
        calls.append((url, options))
        return {'ok': True}

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    client.put_bytes('task-1', 'report.docx', b'PK-test', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    assert calls[0][0] == 'https://site.example/functions/v1/app/internal/artifacts/task-1/report.docx'
    assert calls[0][1]['method'] == 'PUT'
    assert calls[0][1]['headers']['X-Worker-Token'] == 'worker-secret'
    assert calls[0][1]['headers']['Origin'] == 'https://site.example'
    assert calls[0][1]['body'] == b'PK-test'

    with pytest.raises(ValueError, match='filename'):
        client.put_bytes('task-1', '../secret', b'x', 'text/plain')
    with pytest.raises(ValueError, match='HTTPS'):
        SitesStorageClient(origin='http://site.example', shared_secret='x')



@pytest.mark.parametrize(
    'task_id,filename',
    [
        ('task-1', '..%2Fsecret'),
        ('task-1', '%2e%2e%2fsecret'),
        ('task-1', '%252e%252e%252fsecret'),
        ('task-1', '..%5Csecret'),
        ('../task-2', 'report.docx'),
        ('task-1%2F..%2Ftask-2', 'report.docx'),
    ],
)
def test_sites_storage_client_rejects_task_and_filename_traversal_before_transport(task_id, filename):
    calls = []

    def transport(url, options):
        calls.append((url, options))
        return {'body': b'private'}

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    with pytest.raises(ValueError):
        client.get_bytes(task_id, filename)
    assert calls == []


def test_sites_storage_client_percent_encodes_unicode_filename():
    from urllib.parse import quote

    calls = []

    def transport(url, options):
        calls.append((url, options))
        content = b'<html>unicode</html>'
        if '/artifact-checksums/' in url:
            return {
                'body': hashlib.sha256(content).hexdigest().encode('ascii'),
                'content_type': 'text/plain; charset=utf-8',
            }
        return {'body': content, 'content_type': 'text/html'}

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    filename = '研究 报告#终版?.html'
    assert client.get_bytes('task-1', filename) == b'<html>unicode</html>'
    assert calls[0][0].endswith(f'/task-1/{quote(filename, safe="")}')


def test_sites_storage_client_enforces_50_mb_for_upload_and_download():
    exact_content = b'x' * 50_000_000
    too_large = exact_content + b'x'
    calls = []

    def transport(url, options):
        calls.append((url, options))
        if options['method'] == 'GET':
            if '/artifact-checksums/' in url:
                return {
                    'body': hashlib.sha256(exact_content).hexdigest().encode('ascii'),
                    'content_type': 'text/plain; charset=utf-8',
                }
            content = too_large if 'too-large.bin' in url else exact_content
            return {'body': content, 'content_type': 'application/octet-stream'}
        return {'ok': True}

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    client.put_bytes('task-1', 'exact.bin', exact_content, 'application/octet-stream')
    assert client.get_bytes('task-1', 'exact.bin') == exact_content

    too_large = exact_content + b'x'
    with pytest.raises(ValueError, match='50 MB'):
        client.put_bytes('task-1', 'too-large.bin', too_large, 'application/octet-stream')
    with pytest.raises(ValueError, match='50 MB'):
        client.get_bytes('task-1', 'too-large.bin')


@pytest.mark.parametrize('operation', ['put', 'get', 'list'])
def test_sites_storage_client_sanitizes_transport_failures(operation):
    markers = (
        'worker-secret',
        'https://site.example/signed-url',
        'Provider secret response body',
        '/Users/private/server/path',
    )

    def transport(url, options):
        raise TimeoutError(' '.join(markers))

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    with pytest.raises(RuntimeError, match='remote artifact request failed') as caught:
        if operation == 'put':
            client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream')
        elif operation == 'get':
            client.get_bytes('task-1', 'report.docx')
        else:
            client.list('task-1')
    rendered = str(caught.value)
    for marker in markers:
        assert marker not in rendered


def test_sites_storage_client_rejects_non_numeric_status_without_echoing():
    def transport(url, options):
        return {
            'status': 'Provider secret response body',
            'body': b'Provider secret response body /Users/private/server/path',
        }

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    with pytest.raises(RuntimeError, match='remote artifact request failed') as caught:
        client.list('task-1')
    rendered = str(caught.value)
    assert 'Provider secret response body' not in rendered
    assert '/Users/private/server/path' not in rendered


@pytest.mark.parametrize('operation', ['put', 'get', 'list'])
def test_sites_storage_client_rejects_error_responses_without_echoing_provider_body(operation):
    def transport(url, options):
        return {
            'status': 502,
            'error': 'Provider secret response body',
            'body': b'Provider secret response body /Users/private/server/path',
        }

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    with pytest.raises(RuntimeError, match='remote artifact request failed') as caught:
        if operation == 'put':
            client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream')
        elif operation == 'get':
            client.get_bytes('task-1', 'report.docx')
        else:
            client.list('task-1')
    rendered = str(caught.value)
    assert 'Provider secret response body' not in rendered
    assert '/Users/private/server/path' not in rendered
