"""Redact process-only acceptance secrets from textual logs and Playwright traces."""
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [
    ROOT / 'dev' / 'real_backend' / 'runtime',
    ROOT / 'frontend' / 'e2e' / 'real-backend-results',
    ROOT / 'frontend' / 'e2e' / 'real-backend-failures',
]
secrets = [value for key in ('ADMIN_TOKEN', 'SESSION_SECRET') if (value := os.environ.get(key))]


def redact(data):
    for value in secrets:
        data = data.replace(value.encode('utf-8'), b'[redacted-acceptance-secret]')
    return data


changed = []
for target in TARGETS:
    if not target.exists():
        continue
    for path in target.rglob('*'):
        if not path.is_file() or path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webm'}:
            continue
        if path.suffix == '.zip':
            try:
                with zipfile.ZipFile(path) as source:
                    entries = [(item, source.read(item.filename)) for item in source.infolist()]
                redacted = [(item, redact(data)) for item, data in entries]
                if any(data != updated for (_, data), (_, updated) in zip(entries, redacted)):
                    temporary = path.with_suffix('.redacted.zip')
                    with zipfile.ZipFile(temporary, 'w') as output:
                        for item, data in redacted:
                            output.writestr(item, data)
                    temporary.replace(path)
                    changed.append(str(path.relative_to(ROOT)))
                continue
            except zipfile.BadZipFile:
                pass
        try:
            original = path.read_bytes()
        except OSError:
            continue
        updated = redact(original)
        if updated != original:
            path.write_bytes(updated)
            changed.append(str(path.relative_to(ROOT)))
remaining = []
for target in TARGETS:
    if not target.exists():
        continue
    for path in target.rglob('*'):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(value.encode('utf-8') in data for value in secrets):
            remaining.append(str(path.relative_to(ROOT)))
print({'redacted_files': changed, 'files_with_remaining_secret': remaining})
if remaining:
    raise SystemExit(1)
