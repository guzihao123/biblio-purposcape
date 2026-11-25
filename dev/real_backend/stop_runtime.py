import json
import os
from pathlib import Path
import signal
import time

runtime = Path(__file__).resolve().parent / 'runtime' / 'runtime.json'
if runtime.exists():
    pid = json.loads(runtime.read_text(encoding='utf-8'))['runner_pid']
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
