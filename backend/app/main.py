import hashlib
import hmac
import os
import subprocess
import sys
import json
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.answer_validation import read_answer_body
from app.artifacts import ArtifactStore, RemoteArtifact, save_internal_artifact
from app.candidates import CandidateService
from app.config import get_settings
from app.db import SessionLocal, get_db, initialize_database
from app.models import InviteSession, SkillVersion, Task, TaskAnswer, TaskEvent
from app.public_access import create_public_session
from app.queueing import QueueAdapter, QueueEnqueueError, worker_status
from app.orchestration import register_stage_services
from app.rate_limit import (
    RateLimiter,
    enforce_rate_limit,
    get_rate_limiter,
    normalize_idempotency_key,
)
from app.security import require_admin, require_owner, require_session, revoke_session
from app.snapshots import (
    artifact_content_type,
    build_snapshot_payload,
    resolve_snapshot_artifact,
    valid_snapshot_token,
)
from app.skill_versions import SkillVersionError, SkillVersionService
from app.task_flow import answer_card_with_decision
from app.task_presenters import remote_task_payload, task_payload
from app.writing import BODY_FILES
from app.sites_store import MAX_ARTIFACT_BYTES, validate_filename, validate_task_id

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title='Purpose Landscape Web Agent')
initialize_database()
queue_adapter = QueueAdapter()
candidate_service = CandidateService()
register_stage_services()
app.add_api_route('/api/session', create_public_session, methods=['POST'], status_code=201)


@app.put('/api/internal/artifacts/{task_id}/{filename}', status_code=201)
async def put_internal_artifact(
    task_id: str,
    filename: str,
    request: Request,
    x_worker_token: str = Header(default=''),
    db: Session = Depends(get_db),
):
    import hmac

    secret = os.environ.get('WORKER_SHARED_SECRET') or ''
    if not secret or not hmac.compare_digest(x_worker_token, secret):
        raise HTTPException(status_code=403, detail='worker_unauthorized')
    try:
        validate_task_id(task_id)
        validate_filename(filename)
    except ValueError:
        raise HTTPException(status_code=404, detail='Artifact not found') from None
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail='Artifact not found')
    body = await request.body()
    if len(body) > MAX_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail='Artifact too large')
    result = save_internal_artifact(
        task_id,
        filename,
        body,
        request.headers.get('content-type') or 'application/octet-stream',
    )
    return {'ok': True, **result}


@app.get('/api/internal/artifacts/{task_id}')
def list_internal_artifacts(
    task_id: str,
    x_worker_token: str = Header(default=''),
    db: Session = Depends(get_db),
):
    secret = os.environ.get('WORKER_SHARED_SECRET') or ''
    if not secret or not hmac.compare_digest(x_worker_token, secret):
        raise HTTPException(status_code=403, detail='worker_unauthorized')
    try:
        validate_task_id(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail='Artifact not found') from None
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail='Artifact not found')
    store = ArtifactStore()
    directory = store.root / task_id
    artifacts = []
    if directory.is_dir():
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            try:
                store._safe_file(task_id, path.name)
            except HTTPException:
                continue
            artifacts.append(path.name)
    return {'artifacts': artifacts}


@app.get('/api/internal/artifacts/{task_id}/{filename:path}')
def download_internal_artifact(
    task_id: str,
    filename: str,
    x_worker_token: str = Header(default=''),
    db: Session = Depends(get_db),
):
    secret = os.environ.get('WORKER_SHARED_SECRET') or ''
    if not secret or not hmac.compare_digest(x_worker_token, secret):
        raise HTTPException(status_code=403, detail='worker_unauthorized')
    try:
        validate_task_id(task_id)
        validate_filename(filename)
    except ValueError:
        raise HTTPException(status_code=404, detail='Artifact not found') from None
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail='Artifact not found')
    path = ArtifactStore()._safe_file(task_id, filename)
    return FileResponse(path, filename=path.name, content_disposition_type='attachment')


@app.get('/api/health')
def health():
    with SessionLocal() as db:
        db.execute(text('select 1'))
    return {'status': 'ok', 'database': 'ok', 'worker': worker_status()}


def _sites_sync():
    settings = get_settings()
    if settings.task_store_authority != 'sites':
        return None
    from app.sites_task_store import SitesTaskStoreClient
    from app.task_store_sync import TaskStoreSync

    return TaskStoreSync(SitesTaskStoreClient.from_environment())


def _sites_raise(error):
    """Translate a task-store failure without echoing upstream provider text."""
    from app.sites_errors import sites_http_exception

    raise sites_http_exception(error)


def _remote_task(db, task, session):
    sync = _sites_sync()
    candidate_event = None
    version_content = None
    if task.get('next_card') == 'terms':
        candidate_event = sync.get_latest_terms_event(session.id, task['id'])
        if not candidate_event:
            version_content = sync.get_skill_version(session.id, task['skill_version_id']).get('content')
    return remote_task_payload(db, task, candidate_event=candidate_event, version_content=version_content)


def _owned_task(task_id, session, db):
    sync = _sites_sync()
    if sync is not None:
        from types import SimpleNamespace
        try:
            remote = sync.get_task(session.id, task_id)
            return SimpleNamespace(id=remote['id'], session_id=remote['session_id'])
        except Exception as error:
            _sites_raise(error)
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail='Task not found')
    return require_owner(task, session)


def _remote_prepare_terms(sync, task_id, session, limiter, request, answers):
    direction = answers.get('direction', '')
    if isinstance(direction, dict):
        direction = direction.get('direction', '')
    mode = str((answers.get('mode') or {}).get('mode', 'A'))
    previous = sync.get_latest_terms_event(session.id, task_id)
    previous_payload = previous.get('payload', {}) if isinstance(previous, dict) else {}
    if previous_payload.get('direction') == direction and previous_payload.get('mode') == mode:
        return
    candidate_hash = hashlib.sha256(
        json.dumps(
            {'direction': direction, 'mode': mode},
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()
    for operation in ('model', 'retrieval'):
        result = limiter.consume(
            operation,
            session_id=session.id,
            source_ip=limiter.source_ip(request),
            idempotency_key=f'{task_id}:terms-candidates:{candidate_hash}',
        )
        result.raise_if_denied()
    try:
        options = candidate_service.generate(direction, mode)
        sync.append_task_event(
            session.id, task_id, 'terms_candidates',
            f'{task_id}:terms-candidates:{candidate_hash}',
            {'direction': direction, 'mode': mode, 'options': options, 'source': 'model_openalex'},
        )
    except Exception:
        sync.append_task_event(
            session.id, task_id, 'terms_candidates_unavailable',
            f'{task_id}:terms-candidates:{candidate_hash}',
            {
                'direction': direction,
                'mode': mode,
                'message': '候选术语或命中计数暂不可用，请直接输入学术术语。',
            },
        )


def _task_with_idempotency_key(db, session_id, key):
    return db.query(Task).filter_by(
        session_id=session_id,
        idempotency_key=key,
    ).one_or_none()


@app.post('/api/tasks', status_code=201)
def create_task(
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias='Idempotency-Key'),
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    try:
        key = normalize_idempotency_key(idempotency_key) or str(uuid4())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None

    sync = _sites_sync()
    if sync is not None:
        enforce_rate_limit(limiter, 'task_create', request, session_id=None, idempotency_key=key)
        try:
            skill = sync.get_published_skill()
            if skill is None:
                raise HTTPException(status_code=409, detail='no published Skill version is available')
            remote = sync.create_task(
                session_id=session.id,
                task_id=str(uuid4()),
                idempotency_key=key,
                skill_version_id=skill['id'],
                quota={'limit': 3, 'window_seconds': 86400},
            )
            return _remote_task(db, remote, session)
        except Exception as error:
            _sites_raise(error)

    existing = _task_with_idempotency_key(db, session.id, key)
    if existing is not None:
        return task_payload(db, existing)

    enforce_rate_limit(
        limiter,
        'task_create',
        request,
        session_id=session.id,
        idempotency_key=key,
    )
    try:
        active = SkillVersionService(db).active_version()
        if active is None:
            raise SkillVersionError('no published Skill version is available')
        task = Task(
            id=str(uuid4()),
            session_id=session.id,
            skill_version_id=active.id,
            idempotency_key=key,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task_payload(db, task)
    except SkillVersionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except IntegrityError:
        db.rollback()
        existing = _task_with_idempotency_key(db, session.id, key)
        if existing is None:
            raise
        return task_payload(db, existing)


@app.get('/api/tasks')
def list_tasks(
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    sync = _sites_sync()
    if sync is not None:
        try:
            remote = sync.list_tasks(session.id)
            return {'tasks': [_remote_task(db, task, session) for task in remote]}
        except Exception as error:
            _sites_raise(error)
    tasks = db.query(Task).filter_by(session_id=session.id).order_by(Task.created_at.desc()).all()
    return {'tasks': [task_payload(db, task) for task in tasks]}


@app.get('/api/tasks/{task_id}')
def read_task(
    task_id: str,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    sync = _sites_sync()
    if sync is not None:
        try:
            remote = sync.get_task_aggregate(session.id, task_id)
            return _remote_task(db, remote, session)
        except Exception as error:
            _sites_raise(error)
    return task_payload(db, _owned_task(task_id, session, db))


class AnswerRequest(BaseModel):
    value: dict


def _prepare_term_candidates(db, task_id, request, session, limiter):
    direction_answer = db.query(TaskAnswer).filter_by(task_id=task_id, card_id='direction').one()
    mode_answer = db.query(TaskAnswer).filter_by(task_id=task_id, card_id='mode').one()
    direction = direction_answer.value.get('direction', '')
    mode = str(mode_answer.value.get('mode', 'A'))
    previous = db.query(TaskEvent).filter(
        TaskEvent.task_id == task_id,
        TaskEvent.event_type.in_(['terms_candidates', 'terms_candidates_unavailable']),
    ).order_by(TaskEvent.id.desc()).first()
    if previous is not None and previous.payload.get('direction') == direction and previous.payload.get('mode') == mode:
        return

    candidate_hash = hashlib.sha256(
        json.dumps(
            {'direction': direction, 'mode': mode},
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()
    for operation in ('model', 'retrieval'):
        result = limiter.consume(
            operation,
            session_id=session.id,
            source_ip=limiter.source_ip(request),
            idempotency_key=f'{task_id}:terms-candidates:{candidate_hash}',
        )
        result.raise_if_denied()

    try:
        options = candidate_service.generate(direction, mode)
        event = TaskEvent(
            task_id=task_id,
            event_type='terms_candidates',
            payload={'direction': direction, 'mode': mode, 'options': options, 'source': 'model_openalex'},
        )
    except Exception:
        event = TaskEvent(
            task_id=task_id,
            event_type='terms_candidates_unavailable',
            payload={
                'direction': direction,
                'mode': mode,
                'message': '候选术语或命中计数暂不可用，请直接输入学术术语。',
            },
        )
    db.add(event)
    db.commit()


def _task_direction_value(task_id, session, db):
    sync = _sites_sync()
    if sync is not None:
        aggregate = sync.get_task_aggregate(session.id, task_id)
        answers = aggregate.get('answers') or {}
        direction = answers.get('direction') or ''
        if isinstance(direction, dict):
            direction = direction.get('direction', '')
        return str(direction or '').strip()
    answer = db.query(TaskAnswer).filter_by(task_id=task_id, card_id='direction').one_or_none()
    value = answer.value if answer is not None else {}
    return str((value or {}).get('direction') or '').strip()


@app.post('/api/tasks/{task_id}/b-theme-candidates')
def b_theme_candidates(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    _owned_task(task_id, session, db)
    direction = _task_direction_value(task_id, session, db)
    if not direction:
        raise HTTPException(
            status_code=409,
            detail={'code': 'direction_required', 'message': '请先确认研究方向。'},
        )
    digest = hashlib.sha256(direction.encode('utf-8')).hexdigest()[:16]
    enforce_rate_limit(
        limiter,
        'model',
        request,
        session_id=session.id,
        idempotency_key=f'{task_id}:b-themes:{digest}',
    )
    try:
        options = candidate_service.generate_project_themes(direction)
    except Exception:
        options = []
    if not options:
        return {
            'options': [],
            'available': False,
            'message': '项目主题候选暂不可用，可直接自定义项目主题。',
        }
    return {'options': options, 'available': True}


@app.post('/api/tasks/{task_id}/answers/{card_id}')
async def answer_task_card(
    task_id: str,
    card_id: str,
    request: Request,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    value = await read_answer_body(request, card_id)

    sync = _sites_sync()
    if sync is not None:
        try:
            remote = sync.get_task_aggregate(session.id, task_id)
            answer = sync.answer_card(session.id, task_id, card_id, value)
            task = answer['task']
            if answer['changed'] and card_id == 'mode':
                answers = task.get('answers') or {}
                _remote_prepare_terms(sync, task_id, session, limiter, request, answers)
            if answer['changed'] and card_id in ('years', 'delivery'):
                job_kind = 'generate' if card_id == 'delivery' else 'search'
                try:
                    queue_adapter.enqueue_stage(task_id, job_kind, session_id=session.id)
                except QueueEnqueueError as error:
                    raise HTTPException(
                        status_code=503,
                        detail={'code': 'queue_unavailable', 'message': str(error), 'retry_after': 5},
                        headers={'Retry-After': '5'},
                    ) from None
            response = _remote_task(db, task, session)
            response['job_id'] = None
            response['state'] = task['state']
            response['next_card'] = task.get('next_card')
            response['card'] = _remote_task(db, task, session)['card']
            return response
        except Exception as error:
            _sites_raise(error)

    task = _owned_task(task_id, session, db)
    decision = answer_card_with_decision(task.id, card_id, value, session)
    result = decision.result
    db.expire_all()
    if decision.changed and result.next_card and result.next_card.value == 'terms':
        _prepare_term_candidates(db, task.id, request, session, limiter)
    if decision.changed and result.job_id:
        job_kind = 'generate' if card_id == 'delivery' else 'search'
        try:
            queue_adapter.enqueue_stage(task.id, job_kind)
        except QueueEnqueueError as error:
            raise HTTPException(
                status_code=503,
                detail={
                    'code': 'queue_unavailable',
                    'message': str(error),
                    'retry_after': 5,
                },
                headers={'Retry-After': '5'},
            ) from None
    response = task_payload(db, db.get(Task, task.id))
    response['job_id'] = result.job_id
    response['state'] = result.state.value
    response['next_card'] = result.next_card.value if result.next_card else None
    response['card'] = task_payload(db, db.get(Task, task.id))['card']
    return response


@app.get('/api/tasks/{task_id}/artifacts')
def list_task_artifacts(
    task_id: str,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    _owned_task(task_id, session, db)
    return {'artifacts': ArtifactStore().list(task_id, session.id)}


def _artifact_disposition(filename):
    return 'inline' if Path(filename).suffix.lower() in {'.html', '.svg'} else 'attachment'


def _mobile_html_with_signed_image(html, signed_query):
    if not signed_query:
        return html
    suffix = '?' + signed_query
    return html.replace(
        'src="文献图谱仪表盘.png"',
        f'src="文献图谱仪表盘.png{suffix}"',
    ).replace(
        'href="文献图谱仪表盘.png"',
        f'href="文献图谱仪表盘.png{suffix}"',
    )


@app.get('/api/tasks/{task_id}/artifacts/{filename}')
def download_task_artifact(
    task_id: str,
    filename: str,
    signature: str = '',
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    _owned_task(task_id, session, db)
    path = ArtifactStore().resolve(task_id, filename, session.id, signature)
    if isinstance(path, RemoteArtifact):
        image_query = ArtifactStore().signed_url(
            task_id, '文献图谱仪表盘.png', session.id,
        ).split('?', 1)[1]
        content = _mobile_html_with_signed_image(
            path.content.decode('utf-8'), image_query,
        ) if path.filename.lower() == 'mobile.html' else path.content
        return Response(
            content=content,
            media_type=path.content_type,
            headers={
                'Content-Disposition': f'{_artifact_disposition(path.filename)}; filename="{path.filename}"',
                'Cache-Control': 'private, no-store',
            },
        )
    if path.name.lower() == 'mobile.html' and signature:
        image_query = ArtifactStore().signed_url(
            task_id, '文献图谱仪表盘.png', session.id,
        ).split('?', 1)[1]
        return Response(
            content=_mobile_html_with_signed_image(path.read_text(encoding='utf-8'), image_query),
            media_type='text/html; charset=utf-8',
            headers={
                'Content-Disposition': 'inline; filename="mobile.html"',
                'Cache-Control': 'private, no-store',
            },
        )
    return FileResponse(
        path,
        filename=path.name,
        content_disposition_type=_artifact_disposition(path.name),
        headers={'Cache-Control': 'private, no-store'},
    )


@app.get('/api/tasks/{task_id}/dashboard')
def read_task_dashboard(
    task_id: str,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    task = _owned_task(task_id, session, db)
    data_path = ArtifactStore().root / task.id / 'dashboard_data.json'
    data = json.loads(data_path.read_text(encoding='utf-8')) if data_path.is_file() else None
    sync = _sites_sync()
    if sync is not None:
        try:
            remote = sync.get_task_aggregate(session.id, task_id)
            return {
                'task': _remote_task(db, remote, session),
                'data': data,
                'artifacts': ArtifactStore().list(task.id, session.id),
            }
        except Exception as error:
            _sites_raise(error)
    return {
        'task': task_payload(db, task),
        'data': data,
        'artifacts': ArtifactStore().list(task.id, session.id),
    }


@app.get('/api/tasks/{task_id}/report')
def read_task_report(
    task_id: str,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    task = _owned_task(task_id, session, db)
    sync = _sites_sync()
    if sync is not None:
        remote = sync.get_task_aggregate(session.id, task_id)
        mode = str((remote.get('answers') or {}).get('mode', {}).get('mode', 'A'))
    else:
        mode_answer = db.query(TaskAnswer).filter_by(task_id=task.id, card_id='mode').one_or_none()
        mode = str((mode_answer.value if mode_answer else {}).get('mode', 'A'))
    directory = ArtifactStore().root / task.id

    def read_optional(name):
        path = directory / name
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    body_name = BODY_FILES.get(mode, '综述初稿.md')
    body = read_optional(body_name)
    verify = read_optional('verify_report.txt')
    conformance = read_optional('conformance.md')
    return {
        'mode': mode,
        'outline': read_optional('outline.md'),
        'sample': read_optional('sample.md'),
        'body': body,
        'references': body.split('## 参考文献', 1)[1] if '## 参考文献' in body else '',
        'verification': {
            'clean': bool(verify) and '[FAIL]' not in verify and '未通过：' not in conformance,
            'report': verify,
            'conformance': conformance,
        },
        'artifacts': ArtifactStore().list(task.id, session.id),
    }


@app.post('/api/tasks/{task_id}/snapshots')
def create_task_snapshot(
    task_id: str,
    db: Session = Depends(get_db),
    session: InviteSession = Depends(require_session),
):
    task = _owned_task(task_id, session, db)
    return build_snapshot_payload(db, task, ArtifactStore().root)


def _snapshot_task(task_id, token, db):
    task = db.get(Task, task_id)
    if task is None or not valid_snapshot_token(task, token):
        raise HTTPException(status_code=404, detail='Snapshot not found')
    return task


@app.get('/api/snapshots/{task_id}/{token}')
def read_task_snapshot(
    task_id: str,
    token: str,
    db: Session = Depends(get_db),
):
    task = _snapshot_task(task_id, token, db)
    return build_snapshot_payload(db, task, ArtifactStore().root)


@app.get('/api/snapshots/{task_id}/{token}/artifacts/{filename:path}')
def read_snapshot_artifact(
    task_id: str,
    token: str,
    filename: str,
    db: Session = Depends(get_db),
):
    task = _snapshot_task(task_id, token, db)
    try:
        path = resolve_snapshot_artifact(ArtifactStore().root, task.id, filename)
    except ValueError:
        raise HTTPException(status_code=404, detail='Artifact not found') from None
    inline = path.suffix.lower() in {'.html', '.svg'}
    headers = {
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    }
    if inline:
        headers['Content-Security-Policy'] = (
            "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
            "default-src 'self' data: blob: https:; "
            "script-src 'self' 'unsafe-inline' https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https:"
        )
    return FileResponse(
        path,
        filename=path.name,
        media_type=artifact_content_type(path.name),
        content_disposition_type='inline' if inline else 'attachment',
        headers=headers,
    )


@app.post('/api/tasks/{task_id}/resume-generate')
def resume_failed_generate(
    task_id: str,
    x_snapshot_token: str = Header(default=''),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is None or not valid_snapshot_token(task, x_snapshot_token):
        raise HTTPException(status_code=404, detail='Task not found')
    mode_answer = db.query(TaskAnswer).filter_by(task_id=task.id, card_id='mode').one_or_none()
    mode = str((mode_answer.value if mode_answer else {}).get('mode', ''))
    if task.state != 'error' or task.progress is None or task.progress.stage != 'generate' or mode != 'B':
        raise HTTPException(status_code=409, detail='Only a failed B generate stage can be resumed')
    resumed = db.query(TaskEvent).filter(
        TaskEvent.task_id == task.id,
        TaskEvent.event_type == 'generate_resume_requested',
    ).order_by(TaskEvent.id.desc()).first()
    if resumed is not None:
        later_failure = db.query(TaskEvent).filter(
            TaskEvent.task_id == task.id,
            TaskEvent.id > resumed.id,
            TaskEvent.event_type.in_(['failed', 'enqueue_failed']),
        ).first()
        if later_failure is None:
            raise HTTPException(status_code=409, detail='Generate stage was already resumed')
    task.state = 'generating'
    db.commit()
    try:
        queue_adapter.enqueue_stage(task.id, 'generate', session_id=task.session_id)
    except QueueEnqueueError:
        raise HTTPException(status_code=503, detail='Task could not be queued; retry later') from None
    db.add(TaskEvent(
        task_id=task.id,
        event_type='generate_resume_requested',
        payload={'stage': 'generate', 'mode': mode},
    ))
    db.commit()
    return {'queued': True, 'report_url': f'/tasks/{task.id}/report'}


class DraftRequest(BaseModel):
    parent_id: Optional[str] = None
    content: dict


def _version_payload(version):
    return {
        'id': version.id,
        'version': version.version,
        'parent_id': version.parent_id,
        'state': version.state,
        'content': version.content,
        'content_hash': version.content_hash,
        'regression_report': version.regression_report,
    }


def skill_regression_runner(config):
    fixture = PROJECT_ROOT / 'fixtures' / 'hcc-20261122'
    errors = []
    try:
        hcc = subprocess.run(
            [sys.executable, 'verify_delivery.py', '综述初稿.md', '1500-2500', '--mode', 'A'],
            cwd=fixture,
            capture_output=True,
            text=True,
            timeout=120,
        )
        hcc_passed = hcc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        hcc_passed = False
    if not hcc_passed:
        errors.append('HCC evidence regression failed')

    frontend = PROJECT_ROOT / 'frontend'
    npm = os.environ.get('NPM_BINARY', 'npm')
    visual_env = os.environ.copy()
    visual_env['ACCEPTANCE_BACKEND_PORT'] = os.environ.get(
        'REGRESSION_ACCEPTANCE_BACKEND_PORT',
        os.environ.get('ACCEPTANCE_BACKEND_PORT', '8000'),
    )
    visual_env['ACCEPTANCE_FRONTEND_PORT'] = os.environ.get(
        'REGRESSION_ACCEPTANCE_FRONTEND_PORT',
        os.environ.get('ACCEPTANCE_FRONTEND_PORT', '5185'),
    )
    visual_commands = (
        (npm, 'exec', '--', 'playwright', 'test', '--config=playwright.motion.config.ts', 'e2e/motion-components.spec.ts', 'e2e/motion.spec.ts'),
        (npm, 'exec', '--', 'playwright', 'test', 'e2e/task-browser-acceptance.spec.ts'),
    )
    visual_passed = True
    try:
        # Separate fresh fixture databases so earlier scenarios cannot block publication drain checks.
        for command in visual_commands:
            visual = subprocess.run(
                list(command),
                cwd=frontend,
                capture_output=True,
                text=True,
                timeout=240,
                env=visual_env,
            )
            visual_passed = visual_passed and visual.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        visual_passed = False
    if not visual_passed:
        errors.append('Frontend browser regression failed or is unavailable')
    return {
        'passed': not errors,
        'checks': {
            'hcc': 'passed' if hcc_passed else 'failed',
            'frontend_visual': 'passed' if visual_passed else 'failed',
        },
        'errors': errors,
    }


@app.post('/api/admin/sessions/{session_id}/revoke')
def revoke_admin_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    revoke_session(db, session_id)
    return {'revoked': True}


@app.get('/api/admin/skill/versions')
def list_skill_versions(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    versions = db.query(SkillVersion).order_by(SkillVersion.version).all()
    return {'versions': [_version_payload(version) for version in versions]}


@app.post('/api/admin/skill/drafts', status_code=201)
def create_skill_draft(
    payload: DraftRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:
        draft = SkillVersionService(db).create_draft(payload.parent_id, payload.content, actor='admin-api')
    except SkillVersionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _version_payload(draft)


@app.post('/api/admin/skill/versions/{version_id}/regression')
def regress_skill_version(
    version_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:
        report = SkillVersionService(db).run_regression(version_id, skill_regression_runner, actor='admin-api')
    except SkillVersionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return report


@app.post('/api/admin/skill/versions/{version_id}/publish')
def publish_skill_version(
    version_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:
        version = SkillVersionService(db).publish(version_id, actor='admin-api')
    except SkillVersionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _version_payload(version)


@app.post('/api/admin/skill/versions/{version_id}/rollback')
def rollback_skill_version(
    version_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:
        version = SkillVersionService(db).rollback(version_id, actor='admin-api')
    except SkillVersionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _version_payload(version)


@app.get('/{full_path:path}', include_in_schema=False)
def serve_frontend(full_path: str):
    if full_path.startswith('api/'):
        raise HTTPException(status_code=404, detail='Not Found')
    dist = Path(get_settings().frontend_dist).resolve()
    candidate = (dist / full_path).resolve()
    try:
        candidate.relative_to(dist)
    except ValueError:
        raise HTTPException(status_code=404, detail='Not Found') from None
    if candidate.is_file():
        return FileResponse(candidate)
    index = dist / 'index.html'
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail='Not Found')
