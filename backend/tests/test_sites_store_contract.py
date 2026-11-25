import contextlib
import hashlib
import http.server
import json
import threading

import pytest

from app.sites_store import ArtifactIntegrityError, SitesStorageClient, StorageError


class _Recorder:
    def __init__(self, responder):
        self.responder = responder
        self.requests = []


def _handler(recorder):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get('content-length') or 0)
            if length:
                self.rfile.read(length)
            recorder.requests.append({
                'method': self.command,
                'path': self.path,
                'headers': {key.lower(): value for key, value in self.headers.items()},
            })
            status, content_type, body = recorder.responder(self.path)
            self.send_response(status)
            self.send_header('content-type', content_type)
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _reply
        do_PUT = _reply
        do_POST = _reply

        def log_message(self, *args):
            pass

    return Handler


@contextlib.contextmanager
def serving(responder):
    recorder = _Recorder(responder)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _handler(recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d' % server.server_address[1], recorder
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_upload_carries_created_status_and_size_and_sends_origin():
    def responder(path):
        return 201, 'application/json', json.dumps(
            {'ok': True, 'name': 'report.docx', 'size': 4},
        ).encode('utf-8')

    with serving(responder) as (origin, recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        result = client.put_bytes('task-1', 'report.docx', b'PK\x03\x04', 'application/octet-stream')

    assert result['status'] == 201
    assert result['ok'] is True
    assert result['size'] == 4
    assert recorder.requests[0]['method'] == 'PUT'
    assert recorder.requests[0]['headers']['origin'] == origin
    assert recorder.requests[0]['headers']['x-worker-token'] == 'worker-secret'


@pytest.mark.parametrize(
    'status,content_type,body',
    [
        (502, 'text/html', b'<html>Bad Gateway</html>'),
        (403, 'text/plain', b'forbidden'),
        (404, 'application/json', json.dumps({'error': 'not_found'}).encode('utf-8')),
        (500, 'application/json', json.dumps({'ok': True}).encode('utf-8')),
    ],
)
def test_non_2xx_upload_is_always_a_storage_error(status, content_type, body):
    def responder(path):
        return status, content_type, body

    with serving(responder) as (origin, _recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        with pytest.raises(StorageError, match='remote artifact request failed'):
            client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream')


@pytest.mark.parametrize('status', [200, 201])
def test_2xx_non_json_body_is_not_a_successful_json_call(status):
    def responder(path):
        return status, 'text/html', b'<html>sign in</html>'

    with serving(responder) as (origin, _recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        with pytest.raises(StorageError, match='remote artifact request failed'):
            client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream')
        with pytest.raises(StorageError, match='remote artifact request failed'):
            client.list('task-1')


def test_bytes_mode_still_downloads_non_json_artifacts_and_verifies_checksum():
    content = b'<html>dashboard</html>'

    def responder(path):
        if '/artifact-checksums/' in path:
            return 200, 'text/plain; charset=utf-8', hashlib.sha256(content).hexdigest().encode('ascii')
        return 200, 'text/html; charset=utf-8', content

    with serving(responder) as (origin, _recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        assert client.get_bytes('task-1', 'dashboard.html') == content


def test_checksum_mismatch_is_an_integrity_error():
    def responder(path):
        if '/artifact-checksums/' in path:
            return 200, 'text/plain; charset=utf-8', hashlib.sha256(b'other').hexdigest().encode('ascii')
        return 200, 'application/octet-stream', b'PK'

    with serving(responder) as (origin, _recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        with pytest.raises(ArtifactIntegrityError, match='checksum mismatch'):
            client.get_bytes('task-1', 'report.docx')


def test_transport_without_status_keeps_working_for_injected_test_doubles():
    calls = []

    def transport(url, options):
        calls.append((url, options))
        return {'ok': True, 'name': 'report.docx', 'size': 2}

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    assert client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream') == {
        'ok': True,
        'name': 'report.docx',
        'size': 2,
    }
    assert len(calls) == 1


@pytest.mark.parametrize(
    'result',
    [
        {'status': 502, 'body': b'<html>Bad Gateway</html>', 'content_type': 'text/html'},
        {'status': 401, 'ok': True},
        {'body': b'<html>sign in</html>', 'content_type': 'text/html'},
    ],
)
def test_injected_transport_non_2xx_or_html_is_a_storage_error(result):
    def transport(url, options):
        return dict(result)

    client = SitesStorageClient(
        origin='https://site.example',
        shared_secret='worker-secret',
        transport=transport,
    )
    with pytest.raises(StorageError, match='remote artifact request failed'):
        client.put_bytes('task-1', 'report.docx', b'PK', 'application/octet-stream')


def test_list_still_reads_artifacts_from_a_json_payload():
    payload = {'artifacts': [{'name': 'report.docx', 'size': 4}]}

    def responder(path):
        return 200, 'application/json', json.dumps(payload).encode('utf-8')

    with serving(responder) as (origin, _recorder):
        client = SitesStorageClient(origin=origin, shared_secret='worker-secret')
        assert client.list('task-1') == payload['artifacts']
