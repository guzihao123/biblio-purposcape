import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from app.models import SkillVersion, SkillVersionEvent, Task


REQUIRED_CARD_ORDER = ['direction', 'mode', 'terms', 'years', 'adjustment', 'delivery']
ACTIVE_TASK_STATES = (
    'collecting_mode',
    'collecting_terms',
    'collecting_years',
    'searching',
    'dashboard_ready',
    'adjusting',
    'delivery_confirmed',
    'generating',
    'verifying',
)
BASE_VERSION_ROOT = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'versions' / 'base'


def load_base_config():
    template_root = BASE_VERSION_ROOT.parents[1] / 'templates'
    template_files = {
        'A': 'A_调研报告骨架.md',
        'A_DIALOGUE': 'A_对话选题骨架.md',
        'B': 'B_立项依据骨架.md',
        'C1': 'C1_引言段落卡骨架.md',
        'C2': 'C2_文献综述骨架.md',
        'D': 'D_主题调研骨架.md',
        'E': 'A_调研报告骨架.md',
    }
    return {
        'cards': json.loads((BASE_VERSION_ROOT / 'cards.yaml').read_text(encoding='utf-8')),
        'modes': json.loads((BASE_VERSION_ROOT / 'modes.yaml').read_text(encoding='utf-8')),
        'visual': json.loads((BASE_VERSION_ROOT / 'visual.json').read_text(encoding='utf-8')),
        'templates': {
            mode: (template_root / filename).read_text(encoding='utf-8')
            for mode, filename in template_files.items()
        },
    }


class SkillVersionError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _hash(content):
    serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _validate(content):
    if not isinstance(content, dict) or not isinstance(content.get('cards'), dict):
        raise SkillVersionError('cards configuration is required')
    cards = content['cards']
    if cards.get('order') != REQUIRED_CARD_ORDER:
        raise SkillVersionError('confirmation order is locked')
    if cards.get('terms', {}).get('multiple') is not True:
        raise SkillVersionError('terms must remain multi-select')
    if cards.get('adjustment', {}).get('continue_veto') is not True:
        raise SkillVersionError('adjustment continue veto is locked')
    if cards.get('delivery', {}).get('last_confirmation') is not True:
        raise SkillVersionError('delivery must remain the last confirmation')


class SkillVersionService:
    def __init__(self, db):
        self.db = db
        self._serialization_acquired = False

    def _begin_serialized_transaction(self):
        if self.db.in_transaction():
            if self.db.new or self.db.dirty or self.db.deleted:
                raise SkillVersionError('commit pending changes before Skill version transactions')
            self.db.rollback()
        try:
            dialect = self.db.get_bind().dialect.name
            if dialect == 'sqlite':
                self.db.execute(text('BEGIN IMMEDIATE'))
            elif dialect == 'postgresql':
                self.db.execute(text('LOCK TABLE skill_versions IN SHARE ROW EXCLUSIVE MODE'))
        except BaseException:
            self.db.rollback()
            raise

    @contextmanager
    def _serialized_write(self):
        # Version allocation, regression, draining, task pinning and active-
        # version replacement all use one lock and therefore one commit order.
        self._begin_serialized_transaction()
        self._serialization_acquired = True
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._serialization_acquired = False

    def _event(self, version, actor, event_type, diff, regression_report=None):
        self.db.add(SkillVersionEvent(
            version_id=version.id,
            actor=actor,
            event_type=event_type,
            diff=diff,
            regression_report=deepcopy(regression_report),
            created_at=_now(),
        ))

    def _assert_no_active_tasks(self):
        active = self.db.query(Task).filter(Task.state.in_(ACTIVE_TASK_STATES)).count()
        if active:
            raise SkillVersionError(f'active tasks must finish before runtime changes: {active}')

    def active_version(self):
        if not self._serialization_acquired:
            # The API pins tasks after this read and commits in the same session.
            # Hold the lock until that commit so publication cannot drain a gap.
            self._begin_serialized_transaction()
        return self.db.query(SkillVersion).filter_by(state='published').one_or_none()

    def create_draft(self, parent_id, content=None, actor='admin'):
        with self._serialized_write():
            parent = self.db.get(SkillVersion, parent_id) if parent_id else None
            if parent_id and parent is None:
                raise SkillVersionError('parent version does not exist')
            selected = deepcopy(parent.content) if content is None and parent is not None else deepcopy(content)
            _validate(selected)
            next_version = (
                self.db.query(SkillVersion.version)
                .order_by(SkillVersion.version.desc())
                .limit(1)
                .scalar() or 0
            ) + 1
            draft = SkillVersion(
                id=str(uuid4()),
                version=next_version,
                parent_id=parent_id,
                state='draft',
                content=selected,
                content_hash=_hash(selected),
                created_at=_now(),
            )
            self.db.add(draft)
            self.db.flush()
            self._event(draft, actor, 'draft_created', {
                'parent_id': parent_id,
                'content_hash': draft.content_hash,
            })
        self.db.refresh(draft)
        return draft

    def replace_content(self, version_id, content, actor='admin'):
        with self._serialized_write():
            version = self.db.get(SkillVersion, version_id)
            if version is None or version.state != 'draft':
                raise SkillVersionError('published or archived content is immutable')
            _validate(content)
            previous = version.content_hash
            version.content = deepcopy(content)
            version.content_hash = _hash(version.content)
            version.regression_report = None
            self._event(version, actor, 'draft_replaced', {
                'from': previous,
                'to': version.content_hash,
            })
        self.db.refresh(version)
        return version

    def run_regression(self, version_id, runner, actor='admin'):
        with self._serialized_write():
            version = self.db.get(SkillVersion, version_id)
            if version is None or version.state != 'draft':
                raise SkillVersionError('regression requires a draft version')
            report = runner(deepcopy(version.content))
            if not isinstance(report, dict) or not isinstance(report.get('passed'), bool):
                raise SkillVersionError('regression runner must return passed=true or false')
            version.regression_report = deepcopy(report)
            self._event(version, actor, 'regression_completed', {
                'content_hash': version.content_hash,
            }, report)
        return deepcopy(report)

    def publish(self, version_id, actor='admin'):
        with self._serialized_write():
            version = self.db.get(SkillVersion, version_id)
            if version is None:
                raise SkillVersionError('only a draft can be published')
            if version.state == 'published':
                pass
            elif version.state != 'draft':
                raise SkillVersionError('only a draft can be published')
            else:
                if not version.regression_report or version.regression_report.get('passed') is not True:
                    raise SkillVersionError('a passing regression is required before publication')
                self._assert_no_active_tasks()
                current = self.active_version()
                previous_id = current.id if current is not None else None
                if version.parent_id != previous_id:
                    raise SkillVersionError('draft parent is not the active published version')
                if current is not None:
                    current.state = 'archived'
                    self.db.flush()
                version.state = 'published'
                version.published_at = _now()
                self._event(version, actor, 'published', {
                    'active_version': {'from': previous_id, 'to': version.id},
                    'content_hash': {
                        'from': current.content_hash if current is not None else None,
                        'to': version.content_hash,
                    },
                }, version.regression_report)
        self.db.refresh(version)
        return version

    def rollback(self, version_id, actor='admin'):
        with self._serialized_write():
            version = self.db.get(SkillVersion, version_id)
            if version is None:
                raise SkillVersionError('rollback target must be an archived version')
            if version.state == 'published':
                pass
            elif version.state != 'archived':
                raise SkillVersionError('rollback target must be an archived version')
            else:
                if not version.regression_report or version.regression_report.get('passed') is not True:
                    raise SkillVersionError('rollback target has no passing regression')
                self._assert_no_active_tasks()
                current = self.active_version()
                if current is None:
                    raise SkillVersionError('there is no active version to replace')
                previous_id = current.id
                current.state = 'archived'
                self.db.flush()
                version.state = 'published'
                version.published_at = _now()
                self._event(version, actor, 'rolled_back', {
                    'active_version': {'from': previous_id, 'to': version.id},
                }, version.regression_report)
        self.db.refresh(version)
        return version

    def get_task_version(self, task):
        if not task.skill_version_id:
            raise SkillVersionError('task is not pinned to a Skill version')
        version = self.db.get(SkillVersion, task.skill_version_id)
        if version is None:
            raise SkillVersionError('task Skill version is missing')
        return version

    def create_task(self, session_id):
        with self._serialized_write():
            active = self.active_version()
            if active is None:
                raise SkillVersionError('no published Skill version is available')
            task = Task(id=str(uuid4()), session_id=session_id, skill_version_id=active.id)
            self.db.add(task)
        self.db.refresh(task)
        return task

    def history(self):
        return self.db.query(SkillVersionEvent).order_by(SkillVersionEvent.id).all()
