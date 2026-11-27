import json
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import quote

from app.sites_store import MAX_ARTIFACT_BYTES, validate_filename, validate_task_id


def _write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_task_artifacts(task_dir, web_origin, shared_secret, timeout=30):
    task_dir = Path(task_dir)
    if (task_dir / 'papers.json').is_file():
        return 0
    validate_task_id(task_dir.name)
    base = web_origin.rstrip('/')
    headers = {'X-Worker-Token': shared_secret, 'User-Agent': 'purpose-landscape-artifact-rehydrate'}
    list_url = f'{base}/api/internal/artifacts/{quote(task_dir.name, safe="")}'
    request = urllib.request.Request(list_url, headers=headers, method='GET')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode('utf-8'))
    names = payload.get('artifacts')
    if not isinstance(names, list):
        raise ValueError('invalid artifact listing')

    count = 0
    for name in names:
        validate_filename(name)
        url = f'{base}/api/internal/artifacts/{quote(task_dir.name, safe="")}/{quote(name, safe="")}'
        request = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError('artifact exceeds size limit')
        _write_atomic(task_dir / name, content)
        count += 1
    return count
