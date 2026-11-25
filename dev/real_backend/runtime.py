"""Start a real local Redis, FastAPI, RQ worker and Vite frontend."""
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

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'dev' / 'real_backend' / 'runtime'
PYTHON = ROOT / '.venv' / 'bin' / 'python'
REAL_BACKEND_PORT = int(os.environ.get('REAL_BACKEND_PORT', '8000'))
REGRESSION_BACKEND_PORT = REAL_BACKEND_PORT + 1
REGRESSION_FRONTEND_PORT = int(os.environ.get('REGRESSION_ACCEPTANCE_FRONTEND_PORT', '5186'))


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


def main():
    if RUN.exists():
        shutil.rmtree(RUN)
    RUN.mkdir(parents=True)
    (RUN / 'artifacts').mkdir()
    for port in (6389, REAL_BACKEND_PORT, REGRESSION_BACKEND_PORT, 5175, REGRESSION_FRONTEND_PORT):
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
        'REDIS_URL': 'redis://127.0.0.1:6389/0',
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
        spawn('redis', [str(redis_binary), '--bind', '127.0.0.1', '--port', '6389', '--save', '', '--appendonly', 'no', '--dir', str(RUN)])
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
            ['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5175', '--strictPort'],
            cwd=ROOT / 'frontend',
            overrides={'ACCEPTANCE_BACKEND_PORT': str(REAL_BACKEND_PORT)},
        )
        health = wait_http(f'http://127.0.0.1:{REAL_BACKEND_PORT}/api/health')
        wait_http('http://127.0.0.1:5175/')
        time.sleep(1)
        (RUN / 'runtime.json').write_text(json.dumps({
            'frontend': 'http://127.0.0.1:5175',
            'backend': f'http://127.0.0.1:{REAL_BACKEND_PORT}',
            'redis': 'redis://127.0.0.1:6389/0',
            'queue': 'landscape',
            'runner_pid': os.getpid(),
            'processes': {name: process.pid for name, process in zip(('redis', 'web', 'worker', 'frontend'), processes)},
            'provider_boundary': 'offline HCC OpenAlex/statistics/model/reference providers; real app API/SQLite/RQ/graphs/delivery',
            'health': json.loads(health),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REAL_BACKEND_READY http://127.0.0.1:5175', flush=True)
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
            sanitized = subprocess.run(
                [str(PYTHON), 'dev/real_backend/sanitize_artifacts.py'],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            (RUN / 'sanitization.log').write_text(sanitized.stdout + sanitized.stderr, encoding='utf-8')
            (RUN / 'test-exit-code.json').write_text(json.dumps({
                'exit_code': completed.returncode,
                'state_inspection_exit_code': inspected.returncode,
                'sanitization_exit_code': sanitized.returncode,
            }), encoding='utf-8')
            return completed.returncode or inspected.returncode or sanitized.returncode
        while True:
            for name, process in zip(('redis', 'web', 'worker', 'frontend'), processes):
                if process.poll() is not None:
                    raise RuntimeError(f'{name} exited with {process.returncode}')
            time.sleep(1)
    finally:
        cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
