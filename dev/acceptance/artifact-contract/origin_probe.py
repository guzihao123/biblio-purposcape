#!/usr/bin/env python3
"""Records whether backend/app/sites_store.py actually puts Origin on the wire.

Two independent observations:
  1. A loopback capture server sees the real urllib request built by
     SitesStorageClient._request (the production transport).
  2. The Deno function accepts a spoofed Origin, which shows Origin enforcement
     lives in the site gateway, not in sites/functions/index.ts.

Usage: python3 origin_probe.py [--function-origin http://127.0.0.1:8000] [--secret test-secret]
"""

import argparse
import http.client
import http.server
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))

from app.sites_store import SitesStorageClient  # noqa: E402

CAPTURED = []


class Capture(http.server.BaseHTTPRequestHandler):
    def do_PUT(self):  # noqa: N802 - http.server API
        length = int(self.headers.get('content-length') or 0)
        self.rfile.read(length)
        CAPTURED.append({key: value for key, value in self.headers.items()})
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep stdout clean
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--function-origin', default='http://127.0.0.1:8000')
    parser.add_argument('--secret', default='test-secret')
    args = parser.parse_args()

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Capture)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    capture_origin = f'http://127.0.0.1:{port}'

    findings = {}

    client = SitesStorageClient(origin=capture_origin, shared_secret=args.secret)
    client.put_bytes('probe-task', 'probe.bin', b'probe', 'application/octet-stream')
    headers = CAPTURED[0] if CAPTURED else {}
    lowered = {key.lower(): value for key, value in headers.items()}
    findings['origin_header_sent'] = lowered.get('origin')
    findings['all_headers'] = headers

    # A caller-supplied Origin must survive the setdefault().
    client.put_bytes('probe-task', 'probe2.bin', b'probe', 'application/octet-stream')
    client._call(  # noqa: SLF001 - deliberate probe of the internal helper
        f'{capture_origin}/functions/v1/app/internal/artifacts/probe-task/probe3.bin',
        {
            'method': 'PUT',
            'headers': {'X-Worker-Token': args.secret, 'Origin': 'https://caller.example'},
            'body': b'probe',
        },
    )
    second = {key.lower(): value for key, value in CAPTURED[-1].items()}
    findings['caller_origin_preserved'] = second.get('origin')

    server.shutdown()

    # The function itself performs no Origin check: a spoofed Origin still works.
    parsed = urlsplit(args.function_origin)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    conn.request(
        'PUT',
        '/functions/v1/app/internal/artifacts/probe-task/spoof.bin',
        body=b'spoof',
        headers={
            'X-Worker-Token': args.secret,
            'Origin': 'https://evil.example',
            'Content-Type': 'application/octet-stream',
        },
    )
    response = conn.getresponse()
    response.read()
    findings['function_accepts_spoofed_origin_status'] = response.status
    conn.close()

    print(json.dumps(findings, ensure_ascii=False, indent=2))
    Path(__file__).with_name('origin_probe.json').write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    ok = (
        findings['origin_header_sent'] == capture_origin
        and findings['caller_origin_preserved'] == 'https://caller.example'
        and findings['function_accepts_spoofed_origin_status'] == 201
    )
    print('\nOrigin probe:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
