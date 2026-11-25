"""Deterministic expired-signature test for ArtifactStore.resolve.

Monkeypatches itsdangerous.timed's clock (+700s) so a freshly signed URL is
already past its 600 s max_age, then asserts resolve() raises HTTP 403.
Control case (unpatched clock) must succeed against a real fixture file.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path('/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web')
SL = ROOT / 'dev' / 'acceptance' / 'sites-live'
secrets = dict(
    line.split('=', 1)
    for line in (SL / 'data' / 'run-secrets.env').read_text().splitlines()
    if '=' in line
)
os.environ['DATABASE_URL'] = f"sqlite:///{SL / 'data' / 'acceptance.db'}"
os.environ['ARTIFACT_ROOT'] = str(SL / 'data' / 'artifacts')
os.environ['SESSION_SECRET'] = secrets['SESSION_SECRET']

sys.path.insert(0, str(ROOT / 'backend'))

import itsdangerous.timed  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.artifacts import ArtifactStore  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix='sites-live-expiry-'))
task_id = '123e4567-e89b-12d3-a456-426614174099'
(tmp / task_id).mkdir()
(tmp / task_id / 'report.docx').write_bytes(b'PK\x03\x04expiry-fixture')

store = ArtifactStore(root=tmp)
signed = store.signed_url(task_id, 'report.docx', 'session-x')
signature = signed.split('signature=', 1)[1]

control = store.resolve(task_id, 'report.docx', 'session-x', signature)

real_time = itsdangerous.timed.time.time
itsdangerous.timed.time = SimpleNamespace(time=lambda: real_time() + 700)
try:
    try:
        store.resolve(task_id, 'report.docx', 'session-x', signature)
        expired_rejected = False
    except HTTPException as error:
        expired_rejected = error.status_code == 403
finally:
    itsdangerous.timed.time = SimpleNamespace(time=real_time)

print({
    'control_returns_file': Path(control).name == 'report.docx',
    'expired_rejected_403': expired_rejected,
})
sys.exit(0 if expired_rejected else 1)
