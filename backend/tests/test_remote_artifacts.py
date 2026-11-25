from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from fastapi import HTTPException

from app.artifacts import ArtifactStore, RemoteArtifact
from app.config import get_settings


MAX_ARTIFACT_BYTES = 50_000_000
SECRET_MARKERS = (
    'worker-secret',
    'https://site.example/signed-url',
    'Provider secret response body',
    '/Users/private/server/path',
)


class FakeRemote:
    def __init__(self, files=None, get_error=None, list_error=None):
        self.files = files if files is not None else {
            ('task-1', 'report.docx'): b'PK-remote',
            ('task-1', 'desktop.html'): b'<html>remote</html>',
        }
        self.get_error = get_error
        self.list_error = list_error
        self.get_calls = []
        self.list_calls = []

    def list(self, task_id):
        self.list_calls.append(task_id)
        if self.list_error is not None:
            raise self.list_error
        return [
            {'name': name, 'size': len(content)}
            for (task, name), content in self.files.items()
            if task == task_id
        ]

    def get_bytes(self, task_id, filename):
        self.get_calls.append((task_id, filename))
        if self.get_error is not None:
            raise self.get_error
        return self.files[(task_id, filename)]


def make_store(tmp_path, monkeypatch, remote=None):
    monkeypatch.setenv('SESSION_SECRET', 'test-session-secret')
    get_settings.cache_clear()
    return ArtifactStore(root=tmp_path, remote_client=remote)


def sign(store, task_id='task-1', filename='report.docx', session_id='owner-1'):
    return store._serializer().dumps({
        'task_id': task_id,
        'filename': filename,
        'session_id': session_id,
    })


def assert_generic_error(error, status_code):
    assert error.status_code == status_code
    rendered = str(error)
    for marker in SECRET_MARKERS:
        assert marker not in rendered


def test_remote_artifacts_are_listed_and_downloaded_when_local_file_is_missing(tmp_path, monkeypatch):
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)

    listed = store.list('task-1', 'owner-1')
    assert {item['name'] for item in listed} == {'report.docx', 'desktop.html'}

    resolved = store.resolve(
        'task-1', 'report.docx', 'owner-1', sign(store),
    )
    assert resolved.content == b'PK-remote'
    assert resolved.filename == 'report.docx'
    assert remote.get_calls == [('task-1', 'report.docx')]


def test_remote_artifact_wins_over_stale_local_copy_without_mixing_content_or_metadata(tmp_path, monkeypatch):
    (tmp_path / 'task-1').mkdir()
    (tmp_path / 'task-1' / 'report.docx').write_bytes(b'PK-local')
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)

    listed = store.list('task-1', 'owner-1')
    assert next(item for item in listed if item['name'] == 'report.docx')['size'] == len(b'PK-remote')
    resolved = store.resolve(
        'task-1', 'report.docx', 'owner-1', sign(store),
    )
    assert isinstance(resolved, RemoteArtifact)
    assert resolved.content == b'PK-remote'
    assert remote.get_calls == [('task-1', 'report.docx')]


def test_expired_signature_is_rejected_before_remote_fallback(tmp_path, monkeypatch):
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)
    with monkeypatch.context() as time_patch:
        time_patch.setattr('itsdangerous.timed.TimestampSigner.get_timestamp', lambda self: 0)
        expired = sign(store)

    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-1', expired)
    assert_generic_error(caught.value, 403)
    assert remote.get_calls == []


@pytest.mark.parametrize(
    'task_id,filename,session_id',
    [
        ('task-2', 'report.docx', 'owner-1'),
        ('task-1', 'other.docx', 'owner-1'),
        ('task-1', 'report.docx', 'owner-2'),
    ],
    ids=['wrong-task', 'wrong-filename', 'non-owner'],
)
def test_signed_parameter_tampering_is_rejected_before_storage(
    tmp_path, monkeypatch, task_id, filename, session_id,
):
    (tmp_path / 'task-1').mkdir()
    (tmp_path / 'task-1' / 'report.docx').write_bytes(b'private')
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)
    signature = sign(store)

    with pytest.raises(HTTPException) as caught:
        store.resolve(task_id, filename, session_id, signature)
    assert_generic_error(caught.value, 403)
    assert remote.get_calls == []


@pytest.mark.parametrize(
    'filename',
    [
        '../secret',
        '..%2Fsecret',
        '%2e%2e%2fsecret',
        '%252e%252e%252fsecret',
        '..%5Csecret',
    ],
)
def test_path_traversal_and_encoded_traversal_are_rejected_before_remote_fallback(
    tmp_path, monkeypatch, filename,
):
    (tmp_path / 'secret').write_bytes(b'private')
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)

    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', filename, 'owner-1', sign(store, filename=filename))
    assert_generic_error(caught.value, 404)
    assert remote.get_calls == []


@pytest.mark.parametrize('task_id', ['../task-2', 'task-1%2F..%2Ftask-2'])
def test_task_id_traversal_is_rejected_before_local_or_remote_access(
    tmp_path, monkeypatch, task_id,
):
    (tmp_path / 'task-2').mkdir()
    (tmp_path / 'task-2' / 'report.docx').write_bytes(b'private')
    remote = FakeRemote()
    store = make_store(tmp_path, monkeypatch, remote)

    with pytest.raises(HTTPException) as caught:
        store.resolve(task_id, 'report.docx', 'owner-1', sign(store, task_id=task_id))
    assert_generic_error(caught.value, 404)
    assert remote.get_calls == []


@pytest.mark.parametrize(
    'error',
    [
        KeyError('missing'),
        TimeoutError('worker-secret https://site.example/signed-url'),
        RuntimeError('Provider secret response body /Users/private/server/path'),
    ],
    ids=['missing', 'timeout', 'provider-error'],
)
def test_remote_download_failures_are_generic_and_sanitized(tmp_path, monkeypatch, error):
    remote = FakeRemote(get_error=error)
    store = make_store(tmp_path, monkeypatch, remote)

    with pytest.raises(HTTPException) as caught:
        store.resolve('task-1', 'report.docx', 'owner-1', sign(store))
    assert_generic_error(caught.value, 404)


def test_remote_list_failure_does_not_hide_local_artifacts_or_leak_details(tmp_path, monkeypatch):
    (tmp_path / 'task-1').mkdir()
    (tmp_path / 'task-1' / 'local.html').write_bytes(b'<html>local</html>')
    remote = FakeRemote(list_error=RuntimeError(' '.join(SECRET_MARKERS)))
    store = make_store(tmp_path, monkeypatch, remote)

    listed = store.list('task-1', 'owner-1')
    assert [(item['name'], item['size']) for item in listed] == [
        ('local.html', len(b'<html>local</html>')),
    ]


@pytest.mark.parametrize(
    'filename,expected_type',
    [
        ('desktop.html', 'text/html'),
        ('map.svg', 'image/svg+xml'),
        ('report.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
        ('slides.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
        ('unknown.custom-extension', 'application/octet-stream'),
    ],
)
def test_remote_content_type_is_derived_from_artifact_filename(
    tmp_path, monkeypatch, filename, expected_type,
):
    remote = FakeRemote(files={('task-1', filename): b'content'})
    store = make_store(tmp_path, monkeypatch, remote)

    resolved = store.resolve(
        'task-1', filename, 'owner-1', sign(store, filename=filename),
    )
    assert isinstance(resolved, RemoteArtifact)
    assert resolved.content_type == expected_type
    assert resolved.filename == filename


def test_signed_url_percent_encodes_unicode_spaces_and_url_delimiters(tmp_path, monkeypatch):
    filename = '研究 报告#终版?.docx'
    remote = FakeRemote(files={('task-1', filename): b'PK-unicode'})
    store = make_store(tmp_path, monkeypatch, remote)

    url = store.signed_url('task-1', filename, 'owner-1')
    parsed = urlsplit(url)
    assert parsed.path == f'/api/tasks/task-1/artifacts/{quote(filename, safe="")}'
    signature = parse_qs(parsed.query)['signature'][0]
    resolved = store.resolve('task-1', filename, 'owner-1', signature)
    assert resolved.filename == filename
    assert resolved.content == b'PK-unicode'


def test_local_size_limit_includes_exact_50_mb_and_rejects_one_byte_over(tmp_path, monkeypatch):
    directory = tmp_path / 'task-1'
    directory.mkdir()
    for filename, size in [('exact.bin', MAX_ARTIFACT_BYTES), ('too-large.bin', MAX_ARTIFACT_BYTES + 1)]:
        with (directory / filename).open('wb') as artifact:
            artifact.truncate(size)
    store = make_store(tmp_path, monkeypatch)

    exact = store.resolve(
        'task-1', 'exact.bin', 'owner-1', sign(store, filename='exact.bin'),
    )
    assert exact == directory / 'exact.bin'
    with pytest.raises(HTTPException) as caught:
        store.resolve(
            'task-1', 'too-large.bin', 'owner-1', sign(store, filename='too-large.bin'),
        )
    assert_generic_error(caught.value, 404)


def test_remote_size_limit_includes_exact_50_mb_and_rejects_one_byte_over(tmp_path, monkeypatch):
    exact_content = b'x' * MAX_ARTIFACT_BYTES
    remote = FakeRemote(files={
        ('task-1', 'exact.bin'): exact_content,
        ('task-1', 'too-large.bin'): exact_content + b'x',
    })
    store = make_store(tmp_path, monkeypatch, remote)

    exact = store.resolve(
        'task-1', 'exact.bin', 'owner-1', sign(store, filename='exact.bin'),
    )
    assert exact.content == exact_content
    with pytest.raises(HTTPException) as caught:
        store.resolve(
            'task-1', 'too-large.bin', 'owner-1', sign(store, filename='too-large.bin'),
        )
    assert_generic_error(caught.value, 404)
