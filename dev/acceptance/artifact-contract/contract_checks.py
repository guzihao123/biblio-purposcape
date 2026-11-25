#!/usr/bin/env python3
"""Local artifact-contract acceptance for worker -> sites function -> web.

Read-only: talks to an already running `sites/functions/index.ts` (Deno) on
loopback, using the real `backend/app/sites_store.py` client. It never writes
into the repo except its own result.json/ stdout.

Usage:
    python3 dev/acceptance/artifact-contract/contract_checks.py \
        --origin http://127.0.0.1:8000 --secret test-secret [--skip-large]

Exit code 0 only when every non-optional expectation holds.
"""

import argparse
import hashlib
import http.client
import json
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))

from app.sites_store import (  # noqa: E402
    MAX_ARTIFACT_BYTES,
    SitesStorageClient,
    StorageError,
)

RESULTS = []
FAILURES = []


def record(group, name, ok, expected, actual, note=''):
    entry = {
        'group': group,
        'check': name,
        'ok': bool(ok),
        'expected': expected,
        'actual': actual,
        'note': note,
    }
    RESULTS.append(entry)
    if not ok:
        FAILURES.append(entry)
    flag = 'PASS' if ok else 'FAIL'
    print(f'[{flag}] {group:<8} {name}')
    print(f'         expected: {expected}')
    print(f'         actual  : {actual}' + (f'   ({note})' if note else ''))


class Raw:
    """Raw HTTP against the Deno function, preserving status codes."""

    def __init__(self, origin):
        parsed = urlsplit(origin)
        self.host = parsed.hostname
        self.port = parsed.port or 80

    def call(self, method, path, body=None, headers=None, timeout=180):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
            return {
                'status': response.status,
                'headers': {k.lower(): v for k, v in response.getheaders()},
                'body': data,
            }
        finally:
            conn.close()


def worker_headers(secret, extra=None):
    headers = {'X-Worker-Token': secret}
    if extra:
        headers.update(extra)
    return headers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', default='http://127.0.0.1:8000')
    parser.add_argument('--secret', default='test-secret')
    parser.add_argument('--skip-large', action='store_true')
    parser.add_argument('--out', default=str(Path(__file__).parent / 'result.json'))
    args = parser.parse_args()

    origin = args.origin.rstrip('/')
    secret = args.secret
    raw = Raw(origin)
    client = SitesStorageClient(origin=origin, shared_secret=secret)

    payload = '契约验收样例 artifact contract 内容\n'.encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    task = 'accept-task-01'

    # ------------------------------------------------------- client error mapping
    # A gateway 403/502 page is HTML, not JSON. _request() then returns
    # {'body': ..., 'content_type': ...} and _call() has no status to check.
    gateway = SitesStorageClient(
        origin='https://site.example',
        shared_secret=secret,
        transport=lambda url, options: {
            'body': b'<html>502 Bad Gateway</html>',
            'content_type': 'text/html',
        },
    )
    try:
        gateway.put_bytes('task-gw', 'x.bin', b'x', 'application/octet-stream')
        gateway_outcome = 'treated as success'
    except StorageError:
        gateway_outcome = 'StorageError'
    record('client-logic', 'non-JSON gateway error page is not treated as success',
           gateway_outcome == 'StorageError', 'StorageError', gateway_outcome,
           'stub transport, no network')

    # ---------------------------------------------------------------- prefixes
    put_path = f'/functions/v1/app/internal/artifacts/{task}/report.docx'
    created = raw.call('PUT', put_path, payload, worker_headers(secret, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'X-Artifact-SHA256': digest,
    }))
    body = json.loads(created['body'] or b'{}')
    record('prefix', 'PUT /functions/v1/app/... -> 201 + size',
           created['status'] == 201 and body.get('size') == len(payload) and body.get('ok') is True,
           '201 {"ok":true,"size":%d}' % len(payload),
           f"{created['status']} {body}")

    for label, path in [
        ('/app/...', f'/app/internal/artifacts/{task}/report.docx'),
        ('/app-<hash>/...', f'/app-a1b2c3/internal/artifacts/{task}/report.docx'),
        ('/functions/v1/app/app-<hash>/...',
         f'/functions/v1/app/app-a1b2c3/internal/artifacts/{task}/report.docx'),
        ('/app-<hash>/functions/v1/app/...',
         f'/app-a1b2c3/functions/v1/app/internal/artifacts/{task}/report.docx'),
    ]:
        got = raw.call('GET', path, None, worker_headers(secret))
        record('prefix', f'GET {label} download bytes',
               got['status'] == 200 and got['body'] == payload,
               '200 + identical bytes',
               f"{got['status']} {len(got['body'])}B")

    checksum = raw.call(
        'GET', f'/app-a1b2c3/internal/artifact-checksums/{task}/report.docx',
        None, worker_headers(secret),
    )
    record('prefix', 'GET /app-<hash>/internal/artifact-checksums/... ',
           checksum['status'] == 200 and checksum['body'].decode().strip() == digest,
           '200 + sha256 hex',
           f"{checksum['status']} {checksum['body'][:20]!r}")

    listing = raw.call('GET', f'/app/internal/artifacts/{task}', None, worker_headers(secret))
    listed = json.loads(listing['body'] or b'{}')
    record('prefix', 'GET /app/internal/artifacts/<task> list',
           listing['status'] == 200
           and any(item.get('name') == 'report.docx' and item.get('size') == len(payload)
                   for item in listed.get('artifacts', [])),
           '200 {"artifacts":[{"name":"report.docx","size":N}]}',
           f"{listing['status']} {listed}")

    # ------------------------------------------------------------ client roundtrip
    put_result = client.put_bytes(task, 'client.bin', payload, 'application/octet-stream')
    record('client', 'SitesStorageClient.put_bytes',
           put_result.get('ok') is True and put_result.get('size') == len(payload),
           "{'ok': True, 'size': %d}" % len(payload), str(put_result))

    fetched = client.get_bytes(task, 'client.bin')
    record('client', 'SitesStorageClient.get_bytes (checksum verified)',
           fetched == payload, f'{len(payload)}B identical', f'{len(fetched)}B')

    items = client.list(task)
    record('client', 'SitesStorageClient.list',
           {item.get('name') for item in items} >= {'client.bin', 'report.docx'},
           'names contain client.bin + report.docx',
           str(sorted(item.get('name') for item in items)))

    cjk_name = '文献图谱仪表盘.png'
    cjk_payload = b'\x89PNG\r\n\x1a\n' + '中文文件名'.encode('utf-8')
    client.put_bytes(task, cjk_name, cjk_payload, 'image/png')
    record('client', 'non-ASCII filename roundtrip',
           client.get_bytes(task, cjk_name) == cjk_payload,
           'identical bytes for quoted UTF-8 name',
           'identical' if client.get_bytes(task, cjk_name) == cjk_payload else 'mismatch')

    try:
        SitesStorageClient(origin=origin, shared_secret='wrong-secret').get_bytes(task, 'client.bin')
        wrong_secret = 'no exception'
    except Exception as error:  # noqa: BLE001 - contract only cares about rejection
        wrong_secret = type(error).__name__
    record('client', 'wrong shared secret rejected by client',
           wrong_secret == 'StorageError', 'StorageError', wrong_secret)

    try:
        client.put_bytes(task, 'too-big.bin', b'x' * (MAX_ARTIFACT_BYTES + 1), 'application/octet-stream')
        client_guard = 'accepted'
    except ValueError as error:
        client_guard = f'ValueError: {error}'
    record('client', 'client-side >50MB guard (no network)',
           client_guard.startswith('ValueError'), 'ValueError', client_guard)

    # ------------------------------------------------------------------ security
    cases = [
        ('wrong token GET artifact -> 403', 'GET',
         f'/internal/artifacts/{task}/client.bin', None, {'X-Worker-Token': 'nope'}, {403}),
        ('missing token PUT artifact -> 403', 'PUT',
         f'/internal/artifacts/{task}/nope.bin', b'x', {}, {403}),
        ('traversal ..%2Fsecret -> 404', 'GET',
         f'/internal/artifacts/{task}/..%2Fsecret', None, worker_headers(secret), {404}),
        ('traversal %2e%2e%2fsecret -> 404', 'GET',
         f'/internal/artifacts/{task}/%2e%2e%2fsecret', None, worker_headers(secret), {404}),
        ('backslash name a%5Cb -> 404', 'GET',
         f'/internal/artifacts/{task}/a%5Cb', None, worker_headers(secret), {404}),
        ('dot-dot filename -> 404', 'GET',
         f'/internal/artifacts/{task}/%2E%2E', None, worker_headers(secret), {404}),
        ('over-long task id (65) -> 404', 'GET',
         f'/internal/artifacts/{"a" * 65}/x.bin', None, worker_headers(secret), {404}),
        ('POST internal artifact -> 405', 'POST',
         f'/internal/artifacts/{task}/client.bin', b'x', worker_headers(secret), {405}),
        ('DELETE internal artifact -> 405', 'DELETE',
         f'/internal/artifacts/{task}/client.bin', None, worker_headers(secret), {405}),
        ('PUT checksum endpoint -> 405', 'PUT',
         f'/internal/artifact-checksums/{task}/client.bin', b'x', worker_headers(secret), {405}),
        ('POST collection -> 405', 'POST',
         f'/internal/artifacts/{task}', b'x', worker_headers(secret), {405}),
        ('checksum mismatch -> 422', 'PUT',
         f'/internal/artifacts/{task}/bad.bin', payload,
         worker_headers(secret, {'X-Artifact-SHA256': '0' * 64}), {422}),
        ('missing artifact GET -> 404 expected', 'GET',
         f'/internal/artifacts/{task}/does-not-exist.bin', None, worker_headers(secret), {404}),
        ('missing checksum GET -> 404 expected', 'GET',
         f'/internal/artifact-checksums/{task}/does-not-exist.bin', None, worker_headers(secret), {404}),
    ]
    for name, method, path, body_bytes, headers, allowed in cases:
        got = raw.call(method, path, body_bytes, headers)
        record('security', name, got['status'] in allowed,
               f'{sorted(allowed)}', str(got['status']),
               got['body'][:80].decode('utf-8', 'replace'))

    # ------------------------------------------------------- list prefix isolation
    client.put_bytes('task-1', 'a.txt', b'a', 'text/plain')
    client.put_bytes('task-10', 'b.txt', b'b', 'text/plain')
    task1 = client.list('task-1')
    record('isolation', 'list(task-1) excludes task-10 objects',
           {item.get('name') for item in task1} == {'a.txt'},
           "{'a.txt'}", str(sorted(item.get('name') for item in task1)))

    # -------------------------------------------------------------- web forward leg
    web = raw.call('GET', '/functions/v1/app/tasks/11111111-1111-1111-1111-111111111111/artifacts/report.docx')
    record('web', 'web route forwards to Python (dead origin -> 5xx, no local fallback)',
           500 <= web['status'] < 600, '5xx', str(web['status']),
           'PYTHON_API_ORIGIN points at a closed port')

    api = raw.call('GET', '/functions/v1/app/api/tasks/11111111-1111-1111-1111-111111111111/artifacts/report.docx')
    record('web', '/api/... is not routable on the function (web must use /tasks/...)',
           api['status'] == 404, '404', str(api['status']))

    # ------------------------------------------------------------ oversize payload
    if args.skip_large:
        print('[SKIP] security  >50MB server-side guard (--skip-large)')
    else:
        oversize = b'x' * (MAX_ARTIFACT_BYTES + 1)
        try:
            big = raw.call('PUT', f'/internal/artifacts/{task}/oversize.bin', oversize,
                           worker_headers(secret), timeout=180)
            status, note = big['status'], big['body'][:80].decode('utf-8', 'replace')
        except Exception as error:  # noqa: BLE001 - connection reset is a distinct outcome
            status, note = type(error).__name__, 'connection aborted mid-body'
        record('security', 'server-side >50MB guard -> 4xx',
               400 <= (status if isinstance(status, int) else 0) < 500,
               '4xx (413 preferred)', str(status), note)

    # ------------------------------------------------------------------ summary
    total = len(RESULTS)
    passed = sum(1 for item in RESULTS if item['ok'])
    print()
    print(f'{passed}/{total} checks passed, {len(FAILURES)} failed')
    if FAILURES:
        print('failed checks:')
        for item in FAILURES:
            print(f"  - {item['group']}/{item['check']}: expected {item['expected']}, got {item['actual']}")

    Path(args.out).write_text(json.dumps({
        'origin': origin,
        'large_payload_tested': not args.skip_large,
        'total': total,
        'passed': passed,
        'failed': len(FAILURES),
        'checks': RESULTS,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if not FAILURES else 1


if __name__ == '__main__':
    sys.exit(main())
