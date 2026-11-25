import hashlib
import hmac
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import InviteSession, Task


SESSION_COOKIE_NAME = 'invite_session'


class InviteRequest(BaseModel):
    invite_code: str


def create_invite_session(
    invite: InviteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    invite_hash = hashlib.sha256(invite.invite_code.encode()).hexdigest()
    if not hmac.compare_digest(invite_hash, settings.invite_code_hash):
        raise HTTPException(status_code=403, detail='Invalid invite code')

    session = InviteSession(id=str(uuid4()))
    db.add(session)
    db.commit()

    signed_session = URLSafeSerializer(settings.session_secret).dumps(session.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        httponly=True,
        secure=True,
        samesite='lax',
    )
    return {'session_id': session.id}


def require_session(request: Request, db: Session = Depends(get_db)) -> InviteSession:
    signed_session = request.cookies.get(SESSION_COOKIE_NAME, '')
    try:
        session_id = URLSafeSerializer(get_settings().session_secret).loads(signed_session)
    except (BadSignature, TypeError, ValueError):
        raise HTTPException(status_code=401, detail='Invalid session') from None

    if not isinstance(session_id, str):
        raise HTTPException(status_code=401, detail='Invalid session')
    session = db.get(InviteSession, session_id)
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail='Invalid session')

    expires_at = session.expires_at
    if expires_at is None:
        raise HTTPException(status_code=401, detail='Invalid session')
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail='Invalid session')
    return session


def revoke_session(db: Session, session_id: str) -> InviteSession:
    session = db.get(InviteSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return session


def require_owner(task: Task, session: InviteSession) -> Task:
    if task.session_id != session.id:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


def require_admin(x_admin_token: str = Header(default='')) -> None:
    if not hmac.compare_digest(x_admin_token.encode('latin-1'), get_settings().admin_token.encode('utf-8')):
        raise HTTPException(status_code=403, detail='Admin access required')
