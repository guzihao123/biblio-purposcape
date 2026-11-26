import time

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