from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

import app.orchestration as orchestration


class _BrokenSession:
    def __enter__(self):
        raise OperationalError('select', {}, Exception('SSL error: decryption failed or bad record mac'))

    def __exit__(self, *args):
        return False


def test_skill_version_db_failure_falls_back_to_local_base_config(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, 'SessionLocal', lambda: _BrokenSession())
    monkeypatch.setattr(orchestration.engine, 'dispose', lambda: None)
    monkeypatch.setattr(orchestration.time, 'sleep', lambda _seconds: None)
    task = SimpleNamespace(session_id='session', skill_version_id='missing')

    version = orchestration.Orchestrator(artifact_root=tmp_path)._version(task)

    assert version.content['templates']['A']
