from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import URLSafeSerializer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import InviteSession
from app.rate_limit import RateLimiter, enforce_rate_limit, get_rate_limiter
from app.security import SESSION_COOKIE_NAME
from app.task_store_sync import configured_task_store_sync


def _sites_sync():
    from app.sites_task_store import SitesTaskStoreClient
    from app.task_store_sync import TaskStoreSync

    settings = get_settings()
    if settings.task_store_authority != 'sites':
        return None
    return TaskStoreSync(SitesTaskStoreClient.from_environment())


def _sites_raise(error):
    code = getattr(error, 'code', 'task_store_unavailable')
    retry_after = getattr(error, 'retry_after', None)
    status = {'session_not_found': 401, 'skill_version_unavailable': 409, 'quota_exceeded': 429,
              'revision_conflict': 409, 'answer_conflict': 409, 'task_not_found': 404,
              'job_not_found': 404, 'invalid_provider_response': 503}.get(code, 503)
    headers = {'Retry-After': str(retry_after)} if retry_after else {}
    raise HTTPException(status_code=status, detail={'code': code, 'message': str(error)}, headers=headers)


def create_public_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    enforce_rate_limit(limiter, 'session_create', request)
    client_ip = limiter.source_ip(request)
    user_agent = request.headers.get('user-agent', '')[:300]
    session = InviteSession(
        id=str(uuid4()),
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(session)
    db.commit()

    sync = _sites_sync()
    if sync is not None:
        try:
            sync.sync_session(session.id, client_ip=client_ip, user_agent=user_agent)
        except Exception as error:
            _sites_raise(error)

    signed_session = URLSafeSerializer(get_settings().session_secret).dumps(session.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        httponly=True,
        secure=True,
        samesite='lax',
    )
    return {'session_id': session.id}
