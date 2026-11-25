"""Remote listing sanitization and traversal refusal at the web boundary.

Covers the ArtifactStore-side handling of a remote (or a crafted
transport) that returns malformed entries, and pins that traversal
names are rejected before any local or remote access — even when a
remote object with exactly that key exists.
"""

import pytest
from fastapi import HTTPException

from app.sites_store import MAX_ARTIFACT_BYTES

from fakes import (
    FakeQoderStorage,
    make_store_with_transport,
    make_web_store,
    make_worker_client,
    sign,
)


@pytest.mark.parametrize(
    'entries,expected',
    [
        (
            [
                {'name': 'ok.txt', 'size': 3},
                {'name': 'no-size-defaults-to-zero.txt'},
            ],
            {'ok.txt': 3, 'no-size-defaults-to-zero.txt': 0},
        ),
        (
            [
                {'name': '../evil.txt', 'size': 1},
                {'name': 'dir/inside.txt', 'size': 1},
                {'name': 'back\\slash.txt', 'size': 1},
                {'name': '..%2Fencoded.txt', 'size': 1},
            ],
            {},
        ),
        (
            [
                {'name': 'bool-size.txt', 'size': True},
                {'name': 'string-size.txt', 'size': '12'},
                {'name': 'float-size.txt', 'size': 1.5},
                {'name': 'negative-size.txt', 'size': -1},
                {'name': 'over-limit.txt', 'size': MAX_ARTIFACT_BYTES + 1},
            ],
            {},
        ),
        (
            [
                'not-a-mapping',
                {'size': 4},
                {u'name': None, 'size': 1},
                {'name': 'tiny-name-ok.txt', 'size': 0},
            ],
            {'tiny-name-ok.txt': 0},
        ),
    ],
    ids=[
        'valid-and-default-size',
        'traversal-like-names-dropped',
        'invalid-size-types-and-ranges-dropped',
        'non-mapping-and-missing-name-dropped',
    ],
)
def test_malformed_remote_list_entries_are_dropped_not_served(
    tmp_path, monkeypatch, entries, expected,
):
    def junk_transport(url, options):
        return {'artifacts': entries}

    store = make_store_with_transport(tmp_path, monkeypatch, junk_transport)
    (tmp_path / 'task-1').mkdir()
    (tmp_path / 'task-1' / 'local.html').write_bytes(b'<html>local</html>')

    listed = {
        item['name']: item['size']
        for item in store.list('task-1', 'owner-1')
    }
    expected_with_local = dict(expected)
    expected_with_local['local.html'] = len(b'<html>local</html>')
    assert listed == expected_with_local


@pytest.mark.parametrize(
    'filename',
    [
        '../secret',
        '..%2Fsecret',
        '%2e%2e%2fsecret',
        '%252e%252e%252fsecret',
        '..%5Csecret',
        'dir/nested.txt',
        'a%2Fb.txt',
    ],
)
def test_traversal_names_are_rejected_even_when_remote_holds_such_keys(
    tmp_path, monkeypatch, filename,
):
    storage = FakeQoderStorage()
    # A malicious or compromised remote really does hold these keys.
    storage.put('artifacts/task-1/%s' % filename, b'private', 'application/octet-stream')
    storage.put('artifacts/secret', b'private', 'application/octet-stream')

    store = make_web_store(tmp_path, monkeypatch, storage)
    (tmp_path / 'secret').write_bytes(b'private-local')

    with pytest.raises(HTTPException) as caught:
        store.resolve(
            'task-1', filename, 'owner-1',
            sign(store, filename=filename),
        )
    assert caught.value.status_code == 404
    assert store.remote_client.transport.calls == []
    assert (tmp_path / 'secret').read_bytes() == b'private-local'


def test_local_symlink_does_not_replace_authoritative_remote_bytes(tmp_path, monkeypatch):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    worker.put_bytes('task-1', 'report.docx', b'PK-remote', 'application/octet-stream')

    web_fs = tmp_path / 'web'
    (web_fs / 'task-1').mkdir(parents=True)
    (web_fs / 'elsewhere.bin').write_bytes(b'elsewhere')
    (web_fs / 'task-1' / 'report.docx').symlink_to(web_fs / 'elsewhere.bin')

    store = make_web_store(web_fs, monkeypatch, storage)
    resolved = store.resolve('task-1', 'report.docx', 'owner-1', sign(store))
    assert resolved.content == b'PK-remote'


def test_local_symlink_blocks_fallback_when_remote_is_missing(tmp_path, monkeypatch):
    storage = FakeQoderStorage()
    web_fs = tmp_path / 'web'
    (web_fs / 'task-1').mkdir(parents=True)
    (web_fs / 'elsewhere.bin').write_bytes(b'elsewhere')
    (web_fs / 'task-1' / 'report.docx').symlink_to(web_fs / 'elsewhere.bin')

    store = make_web_store(web_fs, monkeypatch, storage)
    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-1', sign(store))
    assert caught.value.status_code == 404
    assert (web_fs / 'elsewhere.bin').read_bytes() == b'elsewhere'
