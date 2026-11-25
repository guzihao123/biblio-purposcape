"""Worker-side artifact production -> remote sync contract, fully offline.

``Orchestrator._sync_artifacts`` builds its own ``SitesStorageClient``
from ``QODER_SITES_ORIGIN`` / ``WORKER_SHARED_SECRET``; the real client
class is kept, only its transport is replaced with the in-process fake,
so URL shape, headers, byte fidelity and the content-type mapping are
all exercised against the real code path.
"""

from urllib.parse import quote

import pytest
from fastapi import HTTPException

import app.orchestration
from app.orchestration import Orchestrator
from app.sites_store import MAX_ARTIFACT_BYTES

from fakes import (
    WORKER_SECRET,
    FakeFunctionsTransport,
    FakeQoderStorage,
    make_web_store,
    sha256_hex,
    sign,
)


@pytest.fixture
def sync_harness(tmp_path, monkeypatch):
    storage = FakeQoderStorage()
    transport = FakeFunctionsTransport(storage, expected_token=WORKER_SECRET)
    real_client = app.orchestration.SitesStorageClient

    def client_factory(origin, shared_secret):
        assert origin == 'https://sites.test'
        assert shared_secret == WORKER_SECRET
        return real_client(
            origin=origin, shared_secret=shared_secret, transport=transport,
        )

    monkeypatch.setattr(app.orchestration, 'SitesStorageClient', client_factory)
    monkeypatch.setenv('QODER_SITES_ORIGIN', 'https://sites.test')
    monkeypatch.setenv('WORKER_SHARED_SECRET', WORKER_SECRET)
    orchestrator = object.__new__(Orchestrator)
    return orchestrator, storage, transport


def test_sync_uploads_every_regular_file_with_bytes_and_content_type(tmp_path, sync_harness):
    orchestrator, storage, transport = sync_harness
    task_dir = tmp_path / 'task-9'
    task_dir.mkdir()
    files = {
        'index.html': '<html>主页</html>'.encode('utf-8'),
        'dashboard_data.json': b'{"series": [1, 2, 3]}',
        'report.docx': b'PK\x03\x04 fake-docx-bytes',
        'slides.pptx': b'PK\x03\x04 fake-pptx-bytes',
        '文献图谱仪表盘.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>'.encode('utf-8'),
        'notes.txt': 'plain notes\n'.encode('utf-8'),
        'blob.unknownext': b'\x00\x01\x02\xff',
        'noextension': b'no extension payload',
    }
    for name, body in files.items():
        (task_dir / name).write_bytes(body)

    assert orchestrator._sync_artifacts(task_dir) == len(files)

    puts = [call for call in transport.calls if call['method'] == 'PUT']
    assert len(puts) == len(files)
    for name, body in files.items():
        object_path = 'artifacts/task-9/%s' % name
        meta = storage.get(object_path)
        assert meta['body'] == body
        assert meta['sha256'] == sha256_hex(body)
        expected_url_suffix = '/internal/artifacts/task-9/%s' % quote(name, safe='')
        recorded = next(
            call for call in puts if call['url'].endswith(expected_url_suffix)
        )
        expected_type = orchestrator._content_type(task_dir / name)
        assert recorded['headers']['Content-Type'] == expected_type
        assert recorded['headers']['X-Worker-Token'] == WORKER_SECRET


def test_sync_skips_oversized_files_without_uploading_them(tmp_path, sync_harness):
    orchestrator, storage, transport = sync_harness
    task_dir = tmp_path / 'task-9'
    task_dir.mkdir()
    with (task_dir / 'huge.bin').open('wb') as oversized:
        oversized.truncate(MAX_ARTIFACT_BYTES + 1)
    (task_dir / 'small.txt').write_bytes(b'small')

    assert orchestrator._sync_artifacts(task_dir) == 1
    assert 'artifacts/task-9/huge.bin' not in storage.objects
    assert storage.get('artifacts/task-9/small.txt')['body'] == b'small'
    assert len([call for call in transport.calls if call['method'] == 'PUT']) == 1


def test_sync_is_a_no_op_without_remote_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv('QODER_SITES_ORIGIN', raising=False)
    monkeypatch.delenv('WORKER_SHARED_SECRET', raising=False)
    orchestrator = object.__new__(Orchestrator)
    task_dir = tmp_path / 'task-9'
    task_dir.mkdir()
    (task_dir / 'report.docx').write_bytes(b'PK-local')

    assert orchestrator._sync_artifacts(task_dir) == 0


def test_worker_to_web_cross_container_flow_shares_bytes_and_nothing_else(
    tmp_path, monkeypatch, sync_harness,
):
    """Full offline E2E: worker filesystem and web filesystem are separate
    directories; only the fake remote joins them."""
    orchestrator, storage, transport = sync_harness
    worker_fs = tmp_path / 'worker-container-fs'
    task_dir = worker_fs / 'task-7'
    task_dir.mkdir(parents=True)
    artifacts = {
        'report.docx': b'PK\x03\x04 cross-container docx bytes',
        'desktop.html': '<html>桌面版</html>'.encode('utf-8'),
        'stats.json': b'{"count": 42}',
    }
    for name, body in artifacts.items():
        (task_dir / name).write_bytes(body)

    assert orchestrator._sync_artifacts(task_dir) == len(artifacts)

    web_fs = tmp_path / 'web-container-fs'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    listed = {item['name']: item['size'] for item in store.list('task-7', 'owner-1')}
    assert listed == {name: len(body) for name, body in artifacts.items()}

    for name, body in artifacts.items():
        resolved = store.resolve(
            'task-7', name, 'owner-1',
            sign(store, task_id='task-7', filename=name),
        )
        assert resolved.content == body
        assert sha256_hex(resolved.content) == sha256_hex(body)

    # The web container never touches the worker filesystem.
    assert not any(str(worker_fs) in call['url'] for call in transport.calls)
