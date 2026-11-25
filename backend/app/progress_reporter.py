"""Stage-level progress reporting for task workers.

The reporter is injected by the worker around a stage invocation. Business
services (retrieval, analysis, writing, delivery) only call ``report_phase``;
they never touch the task store or the UI. Reporting is best effort: a broken
reporter or database must never fail the paid stage it observes.

Only ``TaskProgress.message`` and ``TaskProgress.percent`` are written. The
``stage``, ``input_hash`` and ``checkpoint`` columns stay under the ownership of
the queue lifecycle so duplicate detection and recovery keep working.
"""

from contextvars import ContextVar
from typing import Optional, Protocol, runtime_checkable

from app.models import TaskProgress
from app.recovery import redact_sensitive_text

MAX_MESSAGE_LENGTH = 500

# (stage, name) -> (phase id, user-facing message, percent). Kept in one table
# so the UI and tests can rely on stable, short, whitelisted messages.
PHASES = {
    ('search', 'retrieve'): ('search.retrieve', '正在检索与整理论文池', 10),
    ('search', 'classify'): ('search.classify', '正在分析论文：分类', 25),
    ('search', 'factors'): ('search.factors', '正在分析论文：因素抽取', 35),
    ('search', 'relations'): ('search.relations', '正在分析论文：关系抽取', 45),
    ('search', 'stats'): ('search.stats', '正在统计年度与主题分布', 60),
    ('search', 'graph'): ('search.graph', '正在生成七类图谱', 80),
    ('search', 'upload'): ('search.upload', '正在上传检索产物', 95),
    ('generate', 'components'): ('generate.components', '正在生成构件', 15),
    ('generate', 'outline_sample'): ('generate.outline_sample', '正在生成提纲与样章', 35),
    ('generate', 'body'): ('generate.body', '正在生成正文', 55),
    ('generate', 'review'): ('generate.review', '正在复核交付内容', 70),
    ('generate', 'office'): ('generate.office', '正在生成 Office 交付文件', 85),
    ('generate', 'upload'): ('generate.upload', '正在上传交付产物', 95),
}


@runtime_checkable
class StageReporter(Protocol):
    def update(self, phase: str, message: str, percent: int) -> None:
        ...


class NullReporter:
    """Reporter used when progress persistence is unavailable or unnecessary."""

    def update(self, phase: str, message: str, percent: int) -> None:
        return None


class TaskProgressReporter:
    """Persist phase updates in a short session so pollers see committed rows."""

    def __init__(self, task_id, stage=None, session_factory=None):
        self.task_id = task_id
        self.stage = stage
        self._session_factory = session_factory

    def update(self, phase: str, message: str, percent: int) -> None:
        try:
            from app.db import SessionLocal

            factory = self._session_factory or SessionLocal
            safe_message = redact_sensitive_text(str(message or ''))[:MAX_MESSAGE_LENGTH]
            safe_percent = max(0, min(100, int(percent)))
            with factory() as db:
                progress = db.get(TaskProgress, self.task_id)
                if progress is None:
                    return
                progress.message = safe_message
                progress.percent = safe_percent
                db.commit()
        except Exception:
            # Progress is advisory. Never leak a database diagnostic into the
            # stage result or convert a reporting failure into a task failure.
            pass


_current_reporter: ContextVar[Optional[StageReporter]] = ContextVar(
    'stage_reporter', default=None
)


class stage_reporting:
    """Inject a reporter for one stage execution and restore the prior one."""

    def __init__(self, reporter):
        self.reporter = reporter if reporter is not None else NullReporter()
        self._token = None

    def __enter__(self):
        self._token = _current_reporter.set(self.reporter)
        return self.reporter

    def __exit__(self, exc_type, exc_value, traceback):
        if self._token is not None:
            _current_reporter.reset(self._token)
        return False


def current_reporter():
    return _current_reporter.get() or NullReporter()


def report_phase(phase: str, message: str, percent: int, reporter=None) -> None:
    """Best-effort phase update through the injected reporter."""
    try:
        target = reporter if reporter is not None else current_reporter()
        target.update(phase, message, percent)
    except Exception:
        pass


def report_stage_phase(stage: str, name: str, reporter=None) -> None:
    """Report a named phase from the shared whitelist (no free-form text)."""
    try:
        phase, message, percent = PHASES[(stage, name)]
    except (KeyError, TypeError):
        return
    report_phase(phase, message, percent, reporter=reporter)
