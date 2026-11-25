from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings
from app.sites_store import (
    MAX_ARTIFACT_BYTES,
    ArtifactIntegrityError,
    SitesStorageClient,
    validate_filename,
    validate_task_id,
)


@dataclass
class RemoteArtifact:
    content: bytes
    filename: str
    content_type: str


def save_internal_artifact(task_id, filename, content, content_type, store=None):
    import hashlib
    from tempfile import NamedTemporaryFile

    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError('artifact exceeds the 50 MB limit')
    store = store or ArtifactStore()
    directory = store.root / task_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    with NamedTemporaryFile(dir=directory, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return {
        'name': filename,
        'size': len(content),
        'sha256': hashlib.sha256(content).hexdigest(),
        'content_type': content_type,
    }


class ArtifactStore:
    def __init__(self, root=None, remote_client=None):
        self.root = Path(root or get_settings().artifact_root)
        if remote_client is None and os.environ.get('QODER_SITES_ORIGIN') and os.environ.get('WORKER_SHARED_SECRET'):
            remote_client = SitesStorageClient(
                origin=os.environ['QODER_SITES_ORIGIN'],
                shared_secret=os.environ['WORKER_SHARED_SECRET'],
            )
        self.remote_client = remote_client

    def _serializer(self):
        return URLSafeTimedSerializer(get_settings().session_secret, salt='artifact-download-v1')

    def _validate_identifiers(self, task_id, filename):
        try:
            validate_task_id(task_id)
            validate_filename(filename)
        except ValueError:
            raise HTTPException(status_code=404, detail='Artifact not found') from None

    def _safe_file(self, task_id, filename):
        self._validate_identifiers(task_id, filename)
        path = self.root / task_id / filename
        try:
            root = self.root.resolve(strict=True)
            directory = (self.root / task_id).resolve(strict=True)
            resolved = path.resolve(strict=True)
        except OSError:
            raise HTTPException(status_code=404, detail='Artifact not found') from None
        if (
            directory.parent != root
            or resolved.parent != directory
            or not path.is_file()
            or resolved.stat().st_size > MAX_ARTIFACT_BYTES
        ):
            raise HTTPException(status_code=404, detail='Artifact not found')
        return path

    def signed_url(self, task_id, filename, session_id):
        self._validate_identifiers(task_id, filename)
        signature = self._serializer().dumps({
            'task_id': task_id,
            'filename': filename,
            'session_id': session_id,
        })
        query = urlencode({'signature': signature})
        return (
            f'/api/tasks/{quote(task_id, safe="")}/artifacts/'
            f'{quote(filename, safe="")}?{query}'
        )

    def list(self, task_id, session_id):
        try:
            validate_task_id(task_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='Artifact not found') from None
        directory = self.root / task_id
        artifacts = {}
        if directory.is_dir():
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                try:
                    local_file = self._safe_file(task_id, path.name)
                except HTTPException:
                    continue
                artifacts[path.name] = local_file.stat().st_size
        if self.remote_client is not None:
            try:
                remote_items = self.remote_client.list(task_id)
            except Exception:
                remote_items = []
            for item in remote_items:
                try:
                    name = item['name']
                    validate_filename(name)
                    size = item.get('size', 0)
                    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_ARTIFACT_BYTES:
                        continue
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                artifacts[name] = size
        return [
            {
                'name': name,
                'size': size,
                'url': self.signed_url(task_id, name, session_id),
            }
            for name, size in sorted(artifacts.items())
        ]

    def resolve(self, task_id, filename, session_id, signature):
        try:
            payload = self._serializer().loads(signature, max_age=600)
        except (BadSignature, SignatureExpired, TypeError, ValueError):
            raise HTTPException(status_code=403, detail='Artifact link is invalid or expired') from None
        if payload != {'task_id': task_id, 'filename': filename, 'session_id': session_id}:
            raise HTTPException(status_code=403, detail='Artifact link is invalid or expired')
        self._validate_identifiers(task_id, filename)
        if self.remote_client is not None:
            try:
                content = self.remote_client.get_bytes(task_id, filename)
                if not isinstance(content, bytes) or len(content) > MAX_ARTIFACT_BYTES:
                    raise ValueError('invalid remote artifact')
            except (ArtifactIntegrityError, ValueError):
                raise HTTPException(status_code=404, detail='Artifact not found') from None
            except Exception:
                pass
            else:
                return RemoteArtifact(
                    content=content,
                    filename=filename,
                    content_type=mimetypes.guess_type(filename)[0] or 'application/octet-stream',
                )
        return self._safe_file(task_id, filename)
