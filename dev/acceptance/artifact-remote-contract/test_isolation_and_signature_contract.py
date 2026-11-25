"""Owner isolation, non-owner invisibility and signature strictness.

All cases run against the real web-side ArtifactStore plus the in-memory
fake remote; assertions cover both the observable response and the
transport log (a forbidden request must never reach the remote).
"""

import pytest
from fastapi import HTTPException

from app.config import get_settings

from fakes import (
    WEB_SESSION_SECRET,
    WORKER_SECRET,
    FakeFunctionsTransport,
    FakeQoderStorage,
    make_web_store,
    make_worker_client,
    sign,
)

SECRET_MARKERS = (
    WORKER_SECRET,
    'https://site.example/signed-url',
    'Provider secret response body',
    '/Users/private/server/path',
)


def assert_generic(error, status_code):
    assert error.status_code == status_code
    rendered = str(error)
    for marker in SECRET_MARKERS:
        assert marker not in rendered


def test_remote_listing_and_download_never_leak_other_tasks(tmp_path, monkeypatch):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-aaaa', 'report.docx', b'PK-task-a', 'application/octet-stream')
    worker.put_bytes('task-bbbb', 'report.docx', b'PK-task-b', 'application/octet-stream')
    worker.put_bytes('task-bbbb', 'secret.txt', b'task-b secret', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    listed = store.list('task-aaaa', 'owner-1')
    assert [item['name'] for item in listed] == ['report.docx']

    remote = store.remote_client
    resolved = store.resolve(
        'task-aaaa', 'report.docx', 'owner-1',
        sign(store, task_id='task-aaaa', filename='report.docx'),
    )
    assert resolved.content == b'PK-task-a'
    # Every remote call stayed inside the task-aaaa prefix.
    assert all(
        '/artifacts/task-aaaa' in call['url'] or '/artifact-checksums/task-aaaa' in call['url']
        for call in remote.transport.calls
    )
    assert not any('task-bbbb' in call['url'] for call in remote.transport.calls)


def test_non_owner_with_valid_shape_signature_gets_uniform_403_without_remote_probe(
    tmp_path, monkeypatch,
):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-1', 'report.docx', b'PK-owner-bytes', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    owner_signature = sign(store, session_id='owner-1')
    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-2', owner_signature)
    assert_generic(caught.value, 403)
    assert store.remote_client.transport.calls == []


@pytest.mark.parametrize(
    'signature_kind',
    ['empty', 'garbage', 'extra-payload-key', 'rotated-secret'],
)
def test_signature_strictness_variants_are_rejected_before_remote_access(
    tmp_path, monkeypatch, signature_kind,
):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-1', 'report.docx', b'PK-remote', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    if signature_kind == 'empty':
        signature = ''
    elif signature_kind == 'garbage':
        signature = 'not-a-valid-signature!!!'
    elif signature_kind == 'extra-payload-key':
        signature = store._serializer().dumps({
            'task_id': 'task-1',
            'filename': 'report.docx',
            'session_id': 'owner-1',
            'admin': True,
        })
    else:
        signature = sign(store)
        monkeypatch.setenv('SESSION_SECRET', 'rotated-session-secret')
        get_settings.cache_clear()

    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-1', signature)
    assert_generic(caught.value, 403)
    assert store.remote_client.transport.calls == []


def test_expired_signature_is_rejected_before_remote_access(tmp_path, monkeypatch):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-1', 'report.docx', b'PK-remote', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    with monkeypatch.context() as time_patch:
        time_patch.setattr('itsdangerous.timed.TimestampSigner.get_timestamp', lambda self: 0)
        expired = sign(store)

    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-1', expired)
    assert_generic(caught.value, 403)
    assert store.remote_client.transport.calls == []


def test_wrong_worker_token_maps_to_uniform_404_and_sanitized_listing(tmp_path, monkeypatch):
    """The web side holds an outdated WORKER_SHARED_SECRET: every remote
    request is rejected by the functions surface; the web must surface a
    uniform 404/empty list without leaking the token."""
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-1', 'report.docx', b'PK-remote', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage, presented_secret='outdated-token')

    with pytest.raises(HTTPException) as caught:
        store.resolve(
            'task-1', 'report.docx', 'owner-1', sign(store),
        )
    assert_generic(caught.value, 404)

    # Remote failure must not hide local artifacts, nor leak details.
    (web_fs / 'task-1').mkdir()
    (web_fs / 'task-1' / 'local.html').write_bytes(b'<html>local</html>')
    listed = store.list('task-1', 'owner-1')
    assert [item['name'] for item in listed] == ['local.html']

    # Prove the remote really was probed with the wrong token.
    assert store.remote_client.transport.calls
    assert all(
        call['headers'].get('X-Worker-Token') == 'outdated-token'
        for call in store.remote_client.transport.calls
    )


def test_nonexistent_task_with_valid_signature_is_uniformly_not_found(tmp_path, monkeypatch):
    """Existence oracle check: a signed request for a task that exists
    remotely cannot be distinguished from one that does not."""
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-exists', 'report.docx', b'PK-remote', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    with pytest.raises(HTTPException) as existing:
        store.resolve(
            'task-exists', 'missing.docx', 'owner-1',
            sign(store, task_id='task-exists', filename='missing.docx'),
        )
    with pytest.raises(HTTPException) as missing:
        store.resolve(
            'task-missing', 'report.docx', 'owner-1',
            sign(store, task_id='task-missing', filename='report.docx'),
        )
    assert existing.value.status_code == missing.value.status_code == 404
    assert existing.value.detail == missing.value.detail
