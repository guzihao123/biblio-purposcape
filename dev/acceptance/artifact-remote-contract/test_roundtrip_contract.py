"""Byte-level worker -> remote -> web round-trip contract, fully offline.

Both sides use the real client classes (SitesStorageClient on the worker,
ArtifactStore on the web); only the HTTP transport is faked against an
in-memory Qoder Storage stand-in, so byte fidelity, sizes, SHA-256
digests, filenames and content types are exercised end to end without
any network access.
"""

import hashlib
import io
import json
import random
import zipfile
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from app.artifacts import RemoteArtifact
from app.sites_store import MAX_ARTIFACT_BYTES

from fakes import (
    make_web_store,
    make_worker_client,
    sha256_hex,
    sign,
)


def make_docx_bytes():
    """A structurally real (minimal) OOXML document."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            '[Content_Types].xml',
            '<?xml version="1.0"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        archive.writestr(
            '_rels/.rels',
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            'word/document.xml',
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>跨容器字节往返</w:t></w:r></w:p></w:body></w:document>',
        )
    return buffer.getvalue()


BINARY_PAYLOADS = {
    'all-byte-values.bin': bytes(range(256)) * 4096,              # 1 MiB
    'deterministic-8m.bin': random.Random(20261125).randbytes(8 * 1024 * 1024),
    'report.docx': make_docx_bytes(),
    '综述初稿.md': '# 综述\n\n字节完整性章节\n'.encode('utf-8'),
}


@pytest.mark.parametrize('filename', sorted(BINARY_PAYLOADS))
def test_binary_artifact_round_trips_byte_for_byte_with_matching_sha256(
    tmp_path, monkeypatch, filename,
):
    payload = BINARY_PAYLOADS[filename]
    from fakes import FakeQoderStorage

    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    digest_at_upload = sha256_hex(payload)

    worker.put_bytes('task-1', filename, payload, 'application/octet-stream')
    assert storage.get('artifacts/task-1/%s' % filename)['sha256'] == digest_at_upload

    web_fs = tmp_path / 'web-container-fs'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    listed = store.list('task-1', 'owner-1')
    entry = next(item for item in listed if item['name'] == filename)
    assert entry['size'] == len(payload)

    resolved = store.resolve(
        'task-1', filename, 'owner-1', sign(store, filename=filename),
    )
    assert isinstance(resolved, RemoteArtifact)
    assert resolved.filename == filename
    assert len(resolved.content) == len(payload)
    assert sha256_hex(resolved.content) == digest_at_upload


def test_browser_style_list_then_download_reuses_the_signed_query(tmp_path, monkeypatch):
    from fakes import FakeQoderStorage

    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    payload = b'<html>web dashboard</html>'
    worker.put_bytes('task-1', 'desktop.html', payload, 'text/html; charset=utf-8')

    store = make_web_store(tmp_path / 'web', monkeypatch, storage)
    (tmp_path / 'web').mkdir(exist_ok=True)

    url = store.list('task-1', 'owner-1')[0]['url']
    parsed = urlsplit(url)
    signature = parse_qs(parsed.query)['signature'][0]

    resolved = store.resolve('task-1', 'desktop.html', 'owner-1', signature)
    assert resolved.content == payload
    assert resolved.content_type == 'text/html'


@pytest.mark.parametrize(
    'filename',
    ['研究 报告#终版?.docx', '100% legit.txt', 'data (1).json', 'Ünïcødé.svg'],
)
def test_filenames_with_spaces_percent_and_unicode_round_trip(tmp_path, monkeypatch, filename):
    from fakes import FakeQoderStorage

    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    payload = ('payload-for-%s' % filename).encode('utf-8')
    worker.put_bytes('task-1', filename, payload, 'application/octet-stream')

    store = make_web_store(tmp_path / 'web', monkeypatch, storage)
    (tmp_path / 'web').mkdir(exist_ok=True)

    resolved = store.resolve(
        'task-1', filename, 'owner-1', sign(store, filename=filename),
    )
    assert resolved.filename == filename
    assert resolved.content == payload


def test_exact_50mb_artifact_round_trips_and_one_byte_over_is_rejected(tmp_path, monkeypatch):
    from fakes import FakeQoderStorage

    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    exact = random.Random(7).randbytes(MAX_ARTIFACT_BYTES)
    worker.put_bytes('task-1', 'exact.bin', exact, 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)
    resolved = store.resolve(
        'task-1', 'exact.bin', 'owner-1', sign(store, filename='exact.bin'),
    )
    assert len(resolved.content) == MAX_ARTIFACT_BYTES
    assert sha256_hex(resolved.content) == sha256_hex(exact)

    oversized = b'x' * (MAX_ARTIFACT_BYTES + 1)
    puts_before = len(worker.transport.calls)
    with pytest.raises(ValueError, match='50 MB'):
        worker.put_bytes('task-1', 'too-large.bin', oversized, 'application/octet-stream')
    assert len(worker.transport.calls) == puts_before  # rejected before any request

    # A remote object already stored over the limit must not be downloadable.
    storage.put(
        'artifacts/task-1/oversized-remote.bin', oversized, 'application/octet-stream',
    )
    with pytest.raises(HTTPException) as caught:
        store.resolve(
            'task-1', 'oversized-remote.bin', 'owner-1',
            sign(store, filename='oversized-remote.bin'),
        )
    assert caught.value.status_code == 404


def test_downloaded_content_type_is_derived_from_filename_not_stored_type(tmp_path, monkeypatch):
    """Contract pin: ArtifactStore recomputes Content-Type from the filename.

    The worker's stored content-type is ignored on the web side; the
    served type is filename-derived. This intentionally pins current
    behavior — see the suite report for the divergence note.
    """
    from fakes import FakeQoderStorage

    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes(
        'task-1', 'graph.svg', b'<svg/>', 'application/x-qoder-custom',
    )

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)
    resolved = store.resolve(
        'task-1', 'graph.svg', 'owner-1', sign(store, filename='graph.svg'),
    )
    assert resolved.content_type == 'image/svg+xml'
