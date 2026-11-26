"""Stage heartbeat and bounded hard-stop for worker jobs.

A blocking C call can defeat RQ's SIGALRM job timeout. This watchdog runs in a
separate daemon thread, prints the live Python stacks and RSS periodically, and
terminates the work-horse process once a hard budget is exceeded so a single
stuck call cannot pin the queue forever.
"""

import faulthandler
import os
import sys
import threading
import time
import traceback

DEFAULT_HEARTBEAT_SECONDS = 30.0
DEFAULT_HARD_TIMEOUT_SECONDS = 2700.0
MAX_FRAMES_PER_THREAD = 40


def _env_seconds(name, default):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return value


def _rss_mb():
    try:
        with open('/proc/self/status', encoding='ascii') as status:
            for line in status:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value / (1024.0 * 1024.0) if sys.platform == 'darwin' else value / 1024.0
    except (ImportError, OSError, ValueError):
        return 0.0


def _thread_names():
    return {
        thread.ident: thread.name
        for thread in threading.enumerate()
        if thread.ident is not None
    }


def _format_thread_stacks():
    names = _thread_names()
    lines = []
    for ident, frame in sys._current_frames().items():
        name = names.get(ident, 'unknown')
        lines.append(f'Thread {name} ({ident}):')
        frames = traceback.format_stack(frame)
        if len(frames) > MAX_FRAMES_PER_THREAD:
            omitted = len(frames) - MAX_FRAMES_PER_THREAD
            lines.append(f'  ... {omitted} earlier frames omitted ...')
            frames = frames[-MAX_FRAMES_PER_THREAD:]
        lines.extend(line.rstrip() for line in frames)
    return '\n'.join(lines)


def _emit(text):
    print(text, file=sys.stderr, flush=True)


class StageWatchdog:
    """Context manager that logs stage heartbeats and enforces a hard budget."""

    def __init__(
        self,
        stage,
        task_id,
        heartbeat_seconds=None,
        hard_timeout_seconds=None,
        exit_fn=None,
        on_timeout=None,
        clock=None,
    ):
        self.stage = str(stage)
        self.task_id = str(task_id)
        heartbeat = (
            _env_seconds('STAGE_HEARTBEAT_SECONDS', DEFAULT_HEARTBEAT_SECONDS)
            if heartbeat_seconds is None
            else max(0.0, float(heartbeat_seconds))
        )
        hard_timeout = (
            _env_seconds('STAGE_HARD_TIMEOUT_SECONDS', DEFAULT_HARD_TIMEOUT_SECONDS)
            if hard_timeout_seconds is None
            else max(0.0, float(hard_timeout_seconds))
        )
        self.heartbeat_seconds = heartbeat
        self.hard_timeout_seconds = hard_timeout
        self._exit_fn = exit_fn or os._exit
        self._on_timeout = on_timeout
        self._clock = clock or time.monotonic
        self._started_at = 0.0
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback_obj):
        self.stop()
        return False

    def start(self):
        if self._thread is not None:
            return self
        if self.heartbeat_seconds <= 0 and self.hard_timeout_seconds <= 0:
            return self
        self._started_at = self._clock()
        self._thread = threading.Thread(
            target=self._run,
            name=f'stage-watchdog-{self.stage}',
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=2.0)
        if not thread.is_alive():
            self._thread = None

    def _run(self):
        deadline = (
            self._started_at + self.hard_timeout_seconds
            if self.hard_timeout_seconds > 0
            else None
        )
        next_heartbeat = (
            self._started_at + self.heartbeat_seconds
            if self.heartbeat_seconds > 0
            else None
        )
        while True:
            now = self._clock()
            if deadline is not None and now >= deadline:
                self._hard_timeout(now)
                return
            targets = [value for value in (next_heartbeat, deadline) if value is not None]
            if not targets:
                return
            if self._stop.wait(max(0.01, min(targets) - now)):
                return
            now = self._clock()
            if deadline is not None and now >= deadline:
                self._hard_timeout(now)
                return
            if next_heartbeat is not None and now >= next_heartbeat:
                self._heartbeat(now)
                next_heartbeat += self.heartbeat_seconds
                if next_heartbeat <= now:
                    next_heartbeat = now + self.heartbeat_seconds

    def _header(self, kind, now):
        elapsed = max(0.0, now - self._started_at)
        return (
            f'STAGE {kind} stage={self.stage} task={self.task_id} '
            f'elapsed={elapsed:.1f}s rss={_rss_mb():.1f}MB'
        )

    def _heartbeat(self, now):
        _emit(self._header('HEARTBEAT', now))
        _emit(_format_thread_stacks())

    def _persist_before_exit(self):
        if self._on_timeout is None:
            return

        def persist():
            try:
                self._on_timeout()
            except Exception:
                pass

        worker = threading.Thread(
            target=persist,
            name='stage-watchdog-persist',
            daemon=True,
        )
        worker.start()
        worker.join(timeout=10.0)

    def _hard_timeout(self, now):
        _emit(self._header('HARD TIMEOUT', now))
        _emit(_format_thread_stacks())
        try:
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        except Exception:
            pass
        self._persist_before_exit()
        try:
            sys.stderr.flush()
        except Exception:
            pass
        try:
            self._exit_fn(1)
        except Exception:
            pass