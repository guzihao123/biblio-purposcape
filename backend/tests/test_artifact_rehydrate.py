import json
from pathlib import Path

import pytest

from app.artifact_rehydrate import ensure_task_artifacts


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_rehydrate_skips_when_papers_already_exist(tmp_path, monkeypatch):
    task_dir = tmp_path / 'task-1'
    task_dir.mkdir()
    (task_dir / 'papers.json').write_text('{}', encoding='utf-8')
    calls = []
    monkeypatch.setattr('app.artifact_rehydrate.urllib.request.urlopen', lambda *args, **kwargs: calls.append(args))

    assert ensure_task_artifacts(task_dir, 'https://web.example', 'secret') == 0
    assert calls == []


def test_rehydrate_downloads_existing_artifacts_without_retrieval(tmp_path, monkeypatch):
    task_dir = tmp_path / 'task-1'
    responses = iter([
        FakeResponse(json.dumps({'artifacts': ['papers.json', 'analysis.json', 'search_log.md']}).encode()),
        FakeResponse(b'{"papers": []}'),
        FakeResponse(b'{"limited": {}}'),
        FakeResponse(b'original search log'),
    ])
    requests = []

    def open_request(request, timeout):
        requests.append((request.full_url, request.get_method(), request.get_header('X-worker-token')))
        return next(responses)

    monkeypatch.setattr('app.artifact_rehydrate.urllib.request.urlopen', open_request)

    count = ensure_task_artifacts(task_dir, 'https://web.example/', 'secret')

    assert count == 3
    assert (task_dir / 'papers.json').read_text() == '{"papers": []}'
    assert (task_dir / 'analysis.json').read_text() == '{"limited": {}}'
    assert (task_dir / 'search_log.md').read_text() == 'original search log'
    assert requests[0][0] == 'https://web.example/api/internal/artifacts/task-1'
    assert all(request[1] == 'GET' and request[2] == 'secret' for request in requests)


def test_orchestrator_rehydrates_before_generate_when_worker_disk_is_empty(tmp_path, monkeypatch):
    from app.orchestration import Orchestrator

    task_dir = tmp_path / 'task-1'
    calls = []
    monkeypatch.setenv('WEB_API_ORIGIN', 'https://web.example')
    monkeypatch.setenv('WORKER_SHARED_SECRET', 'secret')
    monkeypatch.setattr(
        'app.artifact_rehydrate.ensure_task_artifacts',
        lambda directory, origin, shared_secret: calls.append((directory, origin, shared_secret)) or 3,
    )

    count = Orchestrator(artifact_root=tmp_path)._rehydrate_task_artifacts(task_dir)

    assert count == 3
    assert calls == [(task_dir, 'https://web.example', 'secret')]


def test_rehydrate_rejects_unsafe_artifact_names(tmp_path, monkeypatch):
    task_dir = tmp_path / 'task-1'
    responses = iter([FakeResponse(json.dumps({'artifacts': ['../secret']}).encode())])
    monkeypatch.setattr('app.artifact_rehydrate.urllib.request.urlopen', lambda *args, **kwargs: next(responses))

    with pytest.raises(ValueError):
        ensure_task_artifacts(task_dir, 'https://web.example', 'secret')

    assert not (tmp_path / 'secret').exists()
