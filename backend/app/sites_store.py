import hashlib
import hmac
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote


MAX_ARTIFACT_BYTES = 50_000_000


class StorageError(RuntimeError):
    pass


class ArtifactIntegrityError(StorageError):
    pass


def validate_task_id(task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', task_id):
        raise ValueError('invalid task_id')


def validate_filename(filename):
    if not isinstance(filename, str) or not filename:
        raise ValueError('invalid filename')
    decoded = filename
    for _ in range(5):
        for value in (filename, decoded):
            if (
                not value
                or value in {'.', '..'}
                or Path(value).name != value
                or '..' in value
                or '/' in value
                or '\\' in value
                or '\x00' in value
            ):
                raise ValueError('invalid filename')
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded


class SitesStorageClient:
    def __init__(self, origin, shared_secret, transport=None):
        self.origin = origin.rstrip('/')
        if not self.origin.startswith('https://') and not self.origin.startswith(('http://127.0.0.1', 'http://localhost')):
            raise ValueError('Qoder Sites origin must use HTTPS')
        if not shared_secret:
            raise ValueError('worker shared secret is required')
        self.shared_secret = shared_secret
        self.transport = transport or self._request

    def _request(self, url, options):
        request = urllib.request.Request(
            url,
            data=options.get('body'),
            method=options.get('method', 'GET'),
            headers=options.get('headers') or {},
        )
        with urllib.request.urlopen(request, timeout=options.get('timeout', 60)) as response:
            body = response.read()
            content_type = response.headers.get('content-type', '')
        if options.get('response_mode') != 'bytes' and 'application/json' in content_type:
            return json.loads(body.decode('utf-8'))
        return {'body': body, 'content_type': content_type}

    def _path(self, task_id, filename):
        validate_task_id(task_id)
        validate_filename(filename)
        return f'/functions/v1/app/internal/artifacts/{quote(task_id, safe="")}/{quote(filename, safe="")}'

    def _checksum_path(self, task_id, filename):
        validate_task_id(task_id)
        validate_filename(filename)
        return f'/functions/v1/app/internal/artifact-checksums/{quote(task_id, safe="")}/{quote(filename, safe="")}'

    def _call(self, url, options):
        headers = dict(options.get('headers') or {})
        # The site gateway rejects server-to-server calls without a site Origin.
        headers.setdefault('Origin', self.origin)
        options = {**options, 'headers': headers}
        try:
            result = self.transport(url, options)
            failed = (
                not isinstance(result, dict)
                or result.get('ok') is False
                or result.get('error') is not None
                or int(result.get('status', 200)) >= 400
            )
        except Exception:
            raise StorageError('remote artifact request failed') from None
        if failed:
            raise StorageError('remote artifact request failed')
        return result

    def put_bytes(self, task_id, filename, content, content_type):
        if not isinstance(content, bytes):
            raise TypeError('content must be bytes')
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError('artifact exceeds the 50 MB limit')
        return self._call(self.origin + self._path(task_id, filename), {
            'method': 'PUT',
            'headers': {
                'X-Worker-Token': self.shared_secret,
                'Content-Type': content_type,
                'X-Artifact-SHA256': hashlib.sha256(content).hexdigest(),
            },
            'body': content,
            'timeout': 120,
        })

    def get_bytes(self, task_id, filename):
        result = self._call(self.origin + self._path(task_id, filename), {
            'method': 'GET',
            'headers': {'X-Worker-Token': self.shared_secret},
            'timeout': 60,
            'response_mode': 'bytes',
        })
        content = result.get('body')
        if not isinstance(content, bytes):
            raise StorageError('remote artifact response is invalid')
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError('artifact exceeds the 50 MB limit')
        try:
            checksum_result = self._call(self.origin + self._checksum_path(task_id, filename), {
                'method': 'GET',
                'headers': {'X-Worker-Token': self.shared_secret},
                'timeout': 60,
                'response_mode': 'bytes',
            })
            checksum_bytes = checksum_result.get('body')
            if not isinstance(checksum_bytes, bytes):
                raise ArtifactIntegrityError('remote artifact checksum is invalid')
            expected = checksum_bytes.decode('ascii').strip()
            if not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ArtifactIntegrityError('remote artifact checksum is invalid')
            actual = hashlib.sha256(content).hexdigest()
            if not hmac.compare_digest(actual, expected):
                raise ArtifactIntegrityError('remote artifact checksum mismatch')
        except ArtifactIntegrityError:
            raise
        except Exception:
            raise ArtifactIntegrityError('remote artifact checksum is unavailable') from None
        return content

    def list(self, task_id):
        validate_task_id(task_id)
        result = self._call(
            f'{self.origin}/functions/v1/app/internal/artifacts/{quote(task_id, safe="")}',
            {
                'method': 'GET',
                'headers': {'X-Worker-Token': self.shared_secret},
                'timeout': 60,
            },
        )
        artifacts = result.get('artifacts')
        if not isinstance(artifacts, list):
            raise StorageError('remote artifact response is invalid')
        return artifacts
