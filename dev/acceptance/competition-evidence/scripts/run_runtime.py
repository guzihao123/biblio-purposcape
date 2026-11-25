"""Independent competition-evidence runtime.

Copied from dev/real_backend/runtime.py with isolated ports and directories:
  - Redis 6394, main API 8026, skill-regression API 8027
  - main frontend 5194, skill-regression frontend 5195
  - run dir: dev/acceptance/competition-evidence/run

Real local Redis, FastAPI, RQ worker and Vite frontend with offline providers.
The shared dev/real_backend/runtime.py and its runtime/ directory are untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import redis
import redislite

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / 'dev' / 'acceptance' / 'competition-evidence'
RUN = EVIDENCE / 'run'
PYTHON = ROOT / '.venv' / 'bin' / 'python'
REAL_BACKEND_PORT = int(os.environ.get('REAL_BACKEND_PORT', '8026'))
REGRESSION_BACKEND_PORT = int(os.environ.get('REGRESSION_ACCEPTANCE_BACKEND_PORT', '8027'))
FRONTEND_PORT = int(os.environ.get('COMPETITION_FRONTEND_PORT', '5194'))
REGRESSION_FRONTEND_PORT = int(os.environ.get('REGRESSION_ACCEPTANCE_FRONTEND_PORT', '5195'))
REDIS_PORT = int(os.environ.get('COMPETITION_REDIS_PORT', '6394'))


def port_open(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) == 0


def wait_http(url, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode('utf-8')
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f'Not ready: {url}')


def sanitize_runtime_logs():
    """Redact process-only secrets from textual files under this run dir."""
    secrets_ = [value for key in ('ADMIN_TOKEN', 'SESSION_SECRET') if (value := os.environ.get(key))]
    changed, remaining = [], []
    for path in sorted(RUN.rglob('*')):
        if not path.is_file() or path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webm'}:
            continue
        try:
            original = path.read_bytes()
        except OSError:
            continue
        updated = original
        for value in secrets_:
            updated = updated.replace(value.encode('utf-8'), b'[redacted-acceptance-secret]')
        if updated != original:
            path.write_bytes(updated)
            changed.append(str(path.relative_to(RUN)))
        if any(value.encode('utf-8') in updated for value in secrets_):
            remaining.append(str(path.relative_to(RUN)))
    (RUN / 'sanitization.log').write_text(
        json.dumps({'redacted_files': changed, 'files_with_remaining_secret': remaining}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    return 1 if remaining else 0


def main():
    if RUN.exists():
        shutil.rmtree(RUN)
    RUN.mkdir(parents=True)
    (RUN / 'artifacts').mkdir()
    (RUN / 'downloads').mkdir()
    for port in (REDIS_PORT, REAL_BACKEND_PORT, REGRESSION_BACKEND_PORT, FRONTEND_PORT, REGRESSION_FRONTEND_PORT):
        if port_open(port):
            raise RuntimeError(f'Port already in use: {port}')
    redis_binary = Path(redislite.__file__).resolve().parent / 'bin' / 'redis-server'
    if not redis_binary.is_file():
        raise RuntimeError(f'redislite server missing: {redis_binary}')
    env = os.environ.copy()
    for name in ('QODER_SITES_ORIGIN', 'WORKER_SHARED_SECRET', 'OPENAI_API_KEY', 'QWEN_API_KEY', 'DASHSCOPE_API_KEY'):
        env.pop(name, None)
    env.update({
        'DATABASE_URL': f'sqlite:///{RUN / "state.sqlite3"}',
        'REDIS_URL': f'redis://127.0.0.1:{REDIS_PORT}/0',
        'ARTIFACT_ROOT': str(RUN / 'artifacts'),
        'SESSION_SECRET': secrets.token_urlsafe(32),
        'ADMIN_TOKEN': secrets.token_urlsafe(32),
        'REGRESSION_ACCEPTANCE_BACKEND_PORT': str(REGRESSION_BACKEND_PORT),
        'REGRESSION_ACCEPTANCE_FRONTEND_PORT': str(REGRESSION_FRONTEND_PORT),
        'PYTHONUNBUFFERED': '1',
    })
    logs, processes = [], []

    def spawn(name, command, cwd=ROOT, overrides=None):
        stream = (RUN / f'{name}.log').open('w', encoding='utf-8')
        logs.append(stream)
        process = subprocess.Popen(command, cwd=cwd, env={**env, **(overrides or {})}, stdout=stream, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    def cleanup(*_):
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 10
        for process in reversed(processes):
            try:
                process.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in logs:
            stream.close()

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
    try:
        spawn('redis', [str(redis_binary), '--bind', '127.0.0.1', '--port', str(REDIS_PORT), '--save', '', '--appendonly', 'no', '--dir', str(RUN)])
        connection = redis.Redis.from_url(env['REDIS_URL'], socket_connect_timeout=1)
        for _ in range(100):
            try:
                if connection.ping():
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError('Redis did not become ready')
        spawn('web', [str(PYTHON), 'dev/real_backend/web_entry.py'], overrides={
            'REAL_BACKEND_PORT': str(REAL_BACKEND_PORT),
        })
        wait_http(f'http://127.0.0.1:{REAL_BACKEND_PORT}/api/health')
        spawn('worker', [str(PYTHON), 'dev/real_backend/worker_entry.py'])
        spawn(
            'frontend',
            ['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(FRONTEND_PORT), '--strictPort'],
            cwd=ROOT / 'frontend',
            overrides={'ACCEPTANCE_BACKEND_PORT': str(REAL_BACKEND_PORT)},
        )
        health = wait_http(f'http://127.0.0.1:{REAL_BACKEND_PORT}/api/health')
        wait_http(f'http://127.0.0.1:{FRONTEND_PORT}/')
        time.sleep(1)
        (RUN / 'runtime.json').write_text(json.dumps({
            'frontend': f'http://127.0.0.1:{FRONTEND_PORT}',
            'backend': f'http://127.0.0.1:{REAL_BACKEND_PORT}',
            'skill_regression_backend': f'http://127.0.0.1:{REGRESSION_BACKEND_PORT}',
            'skill_regression_frontend': f'http://127.0.0.1:{REGRESSION_FRONTEND_PORT}',
            'redis': env['REDIS_URL'],
            'queue': 'landscape',
            'runner_pid': os.getpid(),
            'processes': {name: process.pid for name, process in zip(('redis', 'web', 'worker', 'frontend'), processes)},
            'provider_boundary': 'offline HCC OpenAlex/statistics/model/reference providers; real app API/SQLite/RQ/graphs/delivery',
            'health': json.loads(health),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'COMPETITION_RUNTIME_READY http://127.0.0.1:{FRONTEND_PORT}', flush=True)
        if len(sys.argv) > 1:
            # The child test process receives secrets only through its environment.
            command = sys.argv[2:] if sys.argv[1] == '--' else sys.argv[1:]
            completed = subprocess.run(command, cwd=ROOT / 'frontend', env=env)
            inspected = subprocess.run(
                [str(PYTHON), 'dev/real_backend/inspect_state.py'],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            (RUN / 'state-summary.json').write_text(inspected.stdout, encoding='utf-8')
            (RUN / 'state-inspection.log').write_text(inspected.stderr, encoding='utf-8')
            sanitized = sanitize_runtime_logs()
            (RUN / 'test-exit-code.json').write_text(json.dumps({
                'exit_code': completed.returncode,
                'state_inspection_exit_code': inspected.returncode,
                'sanitization_exit_code': sanitized,
            }), encoding='utf-8')
            return completed.returncode or inspected.returncode or sanitized
        while True:
            for name, process in zip(('redis', 'web', 'worker', 'frontend'), processes):
                if process.poll() is not None:
                    raise RuntimeError(f'{name} exited with {process.returncode}')
            time.sleep(1)
    finally:
        cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
