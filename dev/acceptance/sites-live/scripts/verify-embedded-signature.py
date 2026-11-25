"""Verify the signature embedded in mobile.html targets the PNG itself.

Reads the acceptance run secret from the mode-600 env file, decodes the
embedded signature, and asserts payload binding against the local acceptance
database. Prints only booleans.
"""
import json
import sqlite3
import sys
from pathlib import Path

SL = Path('/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/dev/acceptance/sites-live')
secrets = dict(
    line.split('=', 1)
    for line in (SL / 'data' / 'run-secrets.env').read_text().splitlines()
    if '=' in line
)

from itsdangerous import URLSafeTimedSerializer  # noqa: E402

embedded = (SL / 'data' / 'embedded-signature.txt').read_text().strip()
payload = URLSafeTimedSerializer(secrets['SESSION_SECRET'], salt='artifact-download-v1').loads(
    embedded, max_age=600,
)

db = sqlite3.connect(SL / 'data' / 'acceptance.db')
row = db.execute(
    'select session_id from tasks where id = ?', (payload.get('task_id'),),
).fetchone()

result = {
    'filename_is_png': payload.get('filename') == '文献图谱仪表盘.png',
    'task_exists': row is not None,
    'session_binds_owner_task': row is not None and row[0] == payload.get('session_id'),
    'payload_keys_exact': sorted(payload.keys()) == ['filename', 'session_id', 'task_id'],
}
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if all(result.values()) else 1)
