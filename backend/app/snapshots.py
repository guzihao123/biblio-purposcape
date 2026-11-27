import hashlib
import hmac
import mimetypes
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from app.models import SkillVersion, TaskAnswer, TaskEvent
from app.task_presenters import card_for
from app.writing import BODY_FILES


CARD_STAGES = (
    ('direction', '方向确认'),
    ('mode', '用途确认'),
    ('terms', '术语确认'),
    ('years', '年限确认'),
    ('adjustment', '检索后调整'),
    ('delivery', '交付形式'),
)
PUBLIC_ARTIFACT_NAMES = {
    '综述初稿.docx',
    '标书-文献综述分析.docx',
    '调研报告.docx',
    'report.docx',
    'slides.pptx',
    'dialogue.json',
}


def snapshot_token(task):
    created_at = task.created_at.isoformat() if task.created_at else ''
    seed = '\n'.join((
        'purpose-landscape-readonly-snapshot-v1',
        task.id,
        task.session_id,
        str(task.skill_version_id or ''),
        created_at,
    ))
    return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]


def valid_snapshot_token(task, token):
    return hmac.compare_digest(snapshot_token(task), token)


def _artifact_url(task_id, token, filename):
    return f'/api/snapshots/{task_id}/{token}/artifacts/{quote(filename, safe="")}'


def _public_artifacts(directory, task_id, token):
    if not directory.is_dir():
        return []
    artifacts = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.stat().st_size > 50_000_000:
            continue
        if (
            path.name not in PUBLIC_ARTIFACT_NAMES
            and not path.name.endswith(('.docx', '.pptx'))
        ):
            continue
        artifacts.append({
            'name': path.name,
            'size': path.stat().st_size,
            'url': _artifact_url(task_id, token, path.name),
        })
    return artifacts


def build_snapshot_payload(db, task, artifact_root):
    token = snapshot_token(task)
    answers = {
        row.card_id: row.value
        for row in db.query(TaskAnswer).filter_by(task_id=task.id).order_by(TaskAnswer.id).all()
    }
    mode = str((answers.get('mode') or {}).get('mode', 'A'))
    direction = str((answers.get('direction') or {}).get('direction') or '')
    candidate_event = db.query(TaskEvent).filter(
        TaskEvent.task_id == task.id,
        TaskEvent.event_type == 'terms_candidates',
    ).order_by(TaskEvent.id.desc()).first()
    version = db.get(SkillVersion, task.skill_version_id) if task.skill_version_id else None
    cards = {}
    for stage, title in CARD_STAGES:
        if stage not in answers:
            continue
        surrogate = SimpleNamespace(
            id=task.id,
            next_card=stage,
            skill_version_id=task.skill_version_id,
        )
        cards[stage] = card_for(
            db,
            surrogate,
            answers=answers,
            candidate_event=candidate_event,
            version_content=version.content if version is not None else None,
        )

    directory = Path(artifact_root) / task.id
    body_name = BODY_FILES.get(mode, '综述初稿.md')

    def read_optional(name):
        path = directory / name
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    body = read_optional(body_name)
    checkpoint = task.progress.checkpoint if task.progress is not None else None
    verify = read_optional('verify_report.txt')
    conformance = read_optional('conformance.md')
    clean = bool(checkpoint and checkpoint.get('clean')) and '[FAIL]' not in verify and '未通过：' not in conformance
    dashboard = {
        'desktop_url': _artifact_url(task.id, token, 'desktop.html') if (directory / 'desktop.html').is_file() else None,
        'mobile_url': _artifact_url(task.id, token, 'mobile.html') if (directory / 'mobile.html').is_file() else None,
    }
    stages = [
        {'id': stage, 'title': title, 'available': stage in cards, 'url': f'/snapshots/{task.id}/{token}/{stage}'}
        for stage, title in CARD_STAGES[:4]
    ]
    stages.extend([
        {
            'id': 'search', 'title': '双范围检索', 'available': bool(checkpoint) or bool(dashboard['desktop_url']),
            'url': f'/snapshots/{task.id}/{token}/search',
        },
        {
            'id': 'dashboard', 'title': '七类图谱', 'available': bool(dashboard['desktop_url'] or dashboard['mobile_url']),
            'url': f'/snapshots/{task.id}/{token}/dashboard',
        },
        {
            'id': 'adjustment', 'title': '检索后调整', 'available': 'adjustment' in cards,
            'url': f'/snapshots/{task.id}/{token}/adjustment',
        },
        {
            'id': 'delivery', 'title': '交付形式', 'available': 'delivery' in cards,
            'url': f'/snapshots/{task.id}/{token}/delivery',
        },
        {
            'id': 'report', 'title': '调研交付', 'available': bool(body or read_optional('outline.md')),
            'url': f'/snapshots/{task.id}/{token}/report',
        },
    ])
    return {
        'task_id': task.id,
        'token': token,
        'index_url': f'/snapshots/{task.id}/{token}',
        'direction': direction,
        'mode': mode,
        'state': task.state,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'stages': stages,
        'answers': answers,
        'cards': cards,
        'progress': {
            'stage': task.progress.stage,
            'message': task.progress.message,
            'percent': int(task.progress.percent or 0),
            'checkpoint': checkpoint,
        } if task.progress is not None else None,
        'dashboard': dashboard,
        'report': {
            'mode': mode,
            'outline': read_optional('outline.md'),
            'sample': read_optional('sample.md'),
            'body': body,
            'references': body.split('## 参考文献', 1)[1] if '## 参考文献' in body else '',
            'verification': {'clean': clean, 'report': verify, 'conformance': conformance},
            'artifacts': _public_artifacts(directory, task.id, token),
        },
    }


def resolve_snapshot_artifact(root, task_id, filename):
    if not filename or Path(filename).name != filename or '\\' in filename:
        raise ValueError('invalid artifact filename')
    directory = (Path(root) / task_id).resolve()
    path = (directory / filename).resolve()
    if path.parent != directory or not path.is_file() or path.stat().st_size > 50_000_000:
        raise ValueError('artifact not found')
    return path


def artifact_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
