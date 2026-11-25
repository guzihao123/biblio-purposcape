"""Shared offline fakes for the Render B-02 artifact remote contract suite.

Run from the repository root:

    pytest dev/acceptance/artifact-remote-contract -q

The suite never opens sockets, starts services, or touches the network:
``SitesStorageClient`` (the real worker/web client class) is given a
``transport`` callable that emulates the Qoder Sites Deno functions
surface (``/functions/v1/app/internal/artifacts/...`` as implemented in
``sites/functions/index.ts``) against an in-memory object store.
"""

import hashlib
import json as jsonlib
import re
from urllib.parse import unquote, urlsplit


FUNCTIONS_PREFIX = '/functions/v1/app'
COLLECTION = re.compile(r'^/internal/artifacts/([A-Za-z0-9-]{1,64})$')
OBJECT = re.compile(r'^/internal/artifacts/([A-Za-z0-9-]{1,64})/([^/]+)$')
CHECKSUM_OBJECT = re.compile(r'^/internal/artifact-checksums/([A-Za-z0-9-]{1,64})/([^/]+)$')

WORKER_SECRET = 'acceptance-worker-secret'
WEB_SESSION_SECRET = 'acceptance-web-session-secret'


class FakeQoderStorage:
    """In-memory stand-in for Qoder Storage behind the Deno functions."""

    def __init__(self):
        self.objects = {}

    def put(self, object_path, body, content_type):
        assert isinstance(body, bytes)
        self.objects[object_path] = {
            'body': bytes(body),
            'content_type': content_type or 'application/octet-stream',
            'sha256': hashlib.sha256(body).hexdigest(),
        }

    def get(self, object_path):
        return self.objects[object_path]

    def list(self, prefix):
        return [
            (path, meta)
            for path, meta in sorted(self.objects.items())
            if path.startswith(prefix + '/')
        ]


class FakeFunctionsTransport:
    """Emulates the Qoder Sites Deno functions HTTP surface in-process.

    Mirrors ``sites/functions/index.ts``:
      * ``X-Worker-Token`` digest check happens before routing,
      * collection GET lists ``{name, size}`` under ``artifacts/<task>``,
      * item PUT stores raw bytes plus the request content-type,
      * item GET returns the stored content-type with the raw body.

    The JSON branch of ``SitesStorageClient._request`` is reproduced on
    purpose: when the stored content-type is ``application/json`` the
    transport returns the *parsed* document instead of bytes, exactly as
    the real client would.
    """

    def __init__(self, storage, expected_token):
        self.storage = storage
        self.expected_token = expected_token
        self.calls = []

    def _authorized(self, options):
        supplied = (options.get('headers') or {}).get('X-Worker-Token')
        return isinstance(supplied, str) and supplied == self.expected_token

    def __call__(self, url, options):
        parsed = urlsplit(url)
        self.calls.append({
            'url': url,
            'method': options.get('method', 'GET'),
            'headers': dict(options.get('headers') or {}),
            'body': options.get('body'),
        })
        if not parsed.path.startswith((
            FUNCTIONS_PREFIX + '/internal/artifacts',
            FUNCTIONS_PREFIX + '/internal/artifact-checksums',
        )):
            return {'status': 404, 'error': 'not_found'}
        suffix = parsed.path[len(FUNCTIONS_PREFIX):]
        method = options.get('method', 'GET')
        if not self._authorized(options):
            return {'status': 403, 'error': 'worker_unauthorized'}

        match = CHECKSUM_OBJECT.match(suffix)
        if match:
            task_id, filename = match.group(1), unquote(match.group(2))
            if '..' in filename or '/' in filename or '\\' in filename:
                return {'status': 404, 'error': 'not_found'}
            object_path = 'artifact-checksums/%s/%s' % (task_id, filename)
            if method != 'GET':
                return {'status': 405, 'error': 'method_not_allowed'}
            try:
                meta = self.storage.get(object_path)
            except KeyError:
                return {'status': 404, 'error': 'not_found'}
            return {'body': meta['body'], 'content_type': meta['content_type']}

        match = OBJECT.match(suffix)
        if match:
            task_id, filename = match.group(1), unquote(match.group(2))
            if '..' in filename or '/' in filename or '\\' in filename:
                return {'status': 404, 'error': 'not_found'}
            object_path = 'artifacts/%s/%s' % (task_id, filename)
            if method == 'PUT':
                body = options.get('body') or b''
                checksum = hashlib.sha256(body).hexdigest()
                supplied = (options.get('headers') or {}).get('X-Artifact-SHA256')
                if supplied and supplied != checksum:
                    return {'status': 422, 'error': 'artifact_checksum_mismatch'}
                self.storage.put(
                    'artifact-checksums/%s/%s' % (task_id, filename),
                    checksum.encode('ascii'), 'text/plain; charset=utf-8',
                )
                self.storage.put(
                    object_path, body,
                    (options.get('headers') or {}).get('Content-Type'),
                )
                return {'ok': True, 'name': filename, 'size': len(body)}
            if method == 'GET':
                try:
                    meta = self.storage.get(object_path)
                except KeyError:
                    return {'status': 404, 'error': 'not_found'}
                if options.get('response_mode') != 'bytes' and 'application/json' in meta['content_type']:
                    return jsonlib.loads(meta['body'].decode('utf-8'))
                return {'body': meta['body'], 'content_type': meta['content_type']}
            return {'status': 405, 'error': 'method_not_allowed'}

        match = COLLECTION.match(suffix)
        if match:
            if method != 'GET':
                return {'status': 405, 'error': 'method_not_allowed'}
            prefix = 'artifacts/%s' % match.group(1)
            return {
                'artifacts': [
                    {'name': path[len(prefix) + 1:], 'size': len(meta['body'])}
                    for path, meta in self.storage.list(prefix)
                ]
            }
        return {'status': 404, 'error': 'not_found'}


def make_worker_client(storage, worker_secret=WORKER_SECRET):
    """Worker-side client: the real SitesStorageClient with a fake transport."""
    from app.sites_store import SitesStorageClient

    return SitesStorageClient(
        origin='https://sites.test',
        shared_secret=worker_secret,
        transport=FakeFunctionsTransport(storage, expected_token=WORKER_SECRET),
    )


def make_web_store(tmp_path, monkeypatch, storage, presented_secret=WORKER_SECRET):
    """Web-side ArtifactStore bound to a separate filesystem root.

    ``presented_secret`` is the credential the web container sends; the
    fake remote always expects ``WORKER_SECRET`` (the real remote config),
    so passing a different value emulates an outdated/mismatched token.
    """
    from app.artifacts import ArtifactStore
    from app.config import get_settings
    from app.sites_store import SitesStorageClient

    monkeypatch.setenv('SESSION_SECRET', WEB_SESSION_SECRET)
    get_settings.cache_clear()
    remote = SitesStorageClient(
        origin='https://sites.test',
        shared_secret=presented_secret,
        transport=FakeFunctionsTransport(storage, expected_token=WORKER_SECRET),
    )
    return ArtifactStore(root=tmp_path, remote_client=remote)


def make_store_with_transport(tmp_path, monkeypatch, transport):
    """Web-side ArtifactStore on a caller-supplied transport (junk injection)."""
    from app.artifacts import ArtifactStore
    from app.config import get_settings
    from app.sites_store import SitesStorageClient

    monkeypatch.setenv('SESSION_SECRET', WEB_SESSION_SECRET)
    get_settings.cache_clear()
    remote = SitesStorageClient(
        origin='https://sites.test',
        shared_secret=WORKER_SECRET,
        transport=transport,
    )
    return ArtifactStore(root=tmp_path, remote_client=remote)


def sign(store, **overrides):
    payload = {
        'task_id': 'task-1',
        'filename': 'report.docx',
        'session_id': 'owner-1',
    }
    payload.update(overrides)
    return store._serializer().dumps(payload)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()
