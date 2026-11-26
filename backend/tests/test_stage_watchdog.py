import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from app.stage_watchdog import StageWatchdog


def test_stage_watchdog_emits_heartbeat_with_stack_and_rss(capsys):
    exits = []
    with StageWatchdog(
        'generate',
        'task-1',
        heartbeat_seconds=0.02,
        hard_timeout_seconds=1.0,
        exit_fn=exits.append,
    ):
        time.sleep(0.12)

    captured = capsys.readouterr().err
    assert 'STAGE HEARTBEAT' in captured
    assert 'stage=generate' in captured
    assert 'task=task-1' in captured
    assert 'elapsed=' in captured
    assert 'rss=' in captured
    assert 'Thread' in captured
    assert exits == []


def test_stage_watchdog_hard_timeout_dumps_stack_and_exits(capsys):
    exits = []
    with StageWatchdog(
        'generate',
        'task-2',
        heartbeat_seconds=10.0,
        hard_timeout_seconds=0.05,
        exit_fn=exits.append,
    ):
        time.sleep(0.2)

    captured = capsys.readouterr().err
    assert 'STAGE HARD TIMEOUT' in captured
    assert 'stage=generate' in captured
    assert 'task=task-2' in captured
    assert 'Thread' in captured
    assert exits == [1]


def test_stage_watchdog_persists_state_before_hard_exit(capsys):
    events = []

    def persist():
        events.append('persist')

    def exit_fn(code):
        events.append(('exit', code))

    with StageWatchdog(
        'generate',
        'task-4',
        heartbeat_seconds=10.0,
        hard_timeout_seconds=0.05,
        exit_fn=exit_fn,
        on_timeout=persist,
    ):
        time.sleep(0.2)

    assert events == ['persist', ('exit', 1)]
    assert 'STAGE HARD TIMEOUT' in capsys.readouterr().err


def test_stage_watchdog_timeout_callback_failure_still_exits(capsys):
    events = []

    def persist():
        raise RuntimeError('persistence unavailable')

    with StageWatchdog(
        'generate',
        'task-5',
        heartbeat_seconds=10.0,
        hard_timeout_seconds=0.05,
        exit_fn=lambda code: events.append(code),
        on_timeout=persist,
    ):
        time.sleep(0.2)

    assert events == [1]
    assert 'STAGE HARD TIMEOUT' in capsys.readouterr().err


def test_stage_watchdog_hard_timeout_exits_a_real_process(tmp_path):
    script = textwrap.dedent(
        """
        import time
        from app.stage_watchdog import StageWatchdog

        with StageWatchdog(
            'generate', 'subprocess-task',
            heartbeat_seconds=10,
            hard_timeout_seconds=0.2,
        ):
            time.sleep(30)
        """
    )
    env = dict(os.environ)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'backend')
    completed = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    assert completed.returncode == 1
    assert 'STAGE HARD TIMEOUT' in completed.stderr
    assert 'subprocess-task' in completed.stderr


def test_stage_watchdog_disabled_emits_nothing(capsys):
    exits = []
    with StageWatchdog(
        'generate',
        'task-3',
        heartbeat_seconds=0,
        hard_timeout_seconds=0,
        exit_fn=exits.append,
    ):
        time.sleep(0.05)

    assert capsys.readouterr().err == ''
    assert exits == []