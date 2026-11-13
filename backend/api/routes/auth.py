"""Account registration, token issuance and identity endpoints."""
import re, uuid, threading, time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import settings
from app.database.models import User, SecurityAuditEvent
from app.database.session import get_db
from app.core.security import hash_password, verify_password, create_access_token, require_user, audit

router = APIRouter(prefix="/auth", tags=["authentication"])
_AUTH_LOCK = threading.Lock()
_AUTH_ATTEMPTS: dict[str, list[float]] = {}
_DUMMY_PASSWORD_HASH = hash_password("ARCHEX-DUMMY-ACCOUNT-PASSWORD-2026")

def _client_ip(request: Request) -> str:
    # X-Real-IP is set by the bundled Nginx reverse proxy; direct deployments use the socket peer.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")

def _limit_auth(request: Request):
    key = _client_ip(request)
    now = time.monotonic()
    with _AUTH_LOCK:
        attempts = [stamp for stamp in _AUTH_ATTEMPTS.get(key, []) if now - stamp < 60]
        if len(attempts) >= 12:
            raise HTTPException(429, detail={"code":"auth_rate_limited","message":"Too many authentication attempts. Try again in one minute.","errors":[]})
        attempts.append(now); _AUTH_ATTEMPTS[key] = attempts
        if len(_AUTH_ATTEMPTS) > 2048:
            for stale in [k for k,v in _AUTH_ATTEMPTS.items() if not v or now-v[-1]>=60]: _AUTH_ATTEMPTS.pop(stale,None)

class RegisterInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value): raise ValueError("Enter a valid email address")
        return value
    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value):
        value = value.strip()
        if len(value) < 2: raise ValueError("Display name must contain at least two characters")
        return value
    @field_validator("password")
    @classmethod
    def strong_password(cls, value):
        if not any(c.islower() for c in value) or not any(c.isupper() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include uppercase, lowercase and numeric characters")
        return value

class LoginInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


def user_payload(user: User):
    return {"id":user.id,"email":user.email,"display_name":user.display_name,"role":user.role,"created_at":user.created_at}

@router.get("/config")
def auth_config():
    return {"required":settings.auth_required,"registration_enabled":settings.registration_enabled,
            "token_minutes":settings.auth_token_minutes}

@router.post("/register", status_code=201)
def register(req: RegisterInput, request: Request, db: Session = Depends(get_db)):
    _limit_auth(request)
    if not settings.registration_enabled:
        raise HTTPException(403, detail={"code":"registration_disabled","message":"Registration is disabled","errors":[]})
    if db.scalar(select(User).where(User.email == req.email)):
        raise HTTPException(409, detail={"code":"email_exists","message":"An account with this email already exists","errors":[]})
    now = datetime.now(timezone.utc).isoformat()
    user = User(id=str(uuid.uuid4()), email=req.email, display_name=req.display_name.strip(),
                password_hash=hash_password(req.password), role="researcher", is_active=True,
                created_at=now, updated_at=now)
    db.add(user); db.commit(); db.refresh(user)
    token, expires = create_access_token(user)
    audit(user.id,"account.registered","user",user.id,_client_ip(request))
    return {"access_token":token,"token_type":"bearer","expires_at":expires,"user":user_payload(user)}

@router.post("/login")
def login(req: LoginInput, request: Request, db: Session = Depends(get_db)):
    _limit_auth(request)
    user = db.scalar(select(User).where(User.email == req.email.strip().lower()))
    password_ok = verify_password(req.password, user.password_hash if user is not None else _DUMMY_PASSWORD_HASH)
    if user is None or not user.is_active or not password_ok:
        audit(None,"auth.login_failed","user","",_client_ip(request))
        raise HTTPException(401, detail={"code":"invalid_credentials","message":"Email or password is incorrect","errors":[]},headers={"WWW-Authenticate":"Bearer"})
    token, expires = create_access_token(user)
    audit(user.id,"auth.login","user",user.id,_client_ip(request))
    return {"access_token":token,"token_type":"bearer","expires_at":expires,"user":user_payload(user)}

@router.get("/me")
def me(user: User = Depends(require_user)):
    return user_payload(user)

@router.post("/logout")
def logout(request: Request, user: User = Depends(require_user)):
    audit(user.id,"auth.logout","user",user.id,_client_ip(request))
    # Stateless access tokens expire naturally. Client must discard its token.
    return {"logged_out":True,"token_revocation":"not_supported_until_expiry"}


@router.get("/admin/users")
def admin_users(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(403, detail={"code":"forbidden","message":"Administrator role required","errors":[]})
    rows = db.scalars(select(User).order_by(User.created_at.desc()).limit(500)).all()
    return [user_payload(row) | {"is_active":row.is_active} for row in rows]

@router.patch("/admin/users/{user_id}")
def admin_update_user(user_id: str, request: Request, role: str | None = None, is_active: bool | None = None,
                      user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(403, detail={"code":"forbidden","message":"Administrator role required","errors":[]})
    if role is not None and role not in ("admin", "researcher", "viewer"):
        raise HTTPException(422, detail={"code":"invalid_role","message":"Role must be admin, researcher or viewer","errors":[]})
    target = db.get(User, user_id)
    if target is None: raise HTTPException(404, detail={"code":"not_found","message":"User not found","errors":[]})
    if target.id == user.id and is_active is False: raise HTTPException(409, detail={"code":"self_deactivation","message":"You cannot deactivate your own account","errors":[]})
    if target.role == "admin" and ((role is not None and role != "admin") or is_active is False):
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(409, detail={"code":"last_admin_required","message":"At least one active administrator must remain","errors":[]})
    if role is not None: target.role = role
    if is_active is not None: target.is_active = is_active
    target.updated_at = datetime.now(timezone.utc).isoformat(); db.commit(); db.refresh(target)
    audit(user.id,"admin.user_updated","user",target.id,_client_ip(request))
    return user_payload(target) | {"is_active":target.is_active}

@router.get("/admin/audit")
def admin_audit(limit: int = 100, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(403, detail={"code":"forbidden","message":"Administrator role required","errors":[]})
    rows = db.scalars(select(SecurityAuditEvent).order_by(SecurityAuditEvent.id.desc()).limit(max(1,min(limit,500)))).all()
    return [{"id":r.id,"user_id":r.user_id,"action":r.action,"resource_type":r.resource_type,
             "resource_id":r.resource_id,"ip_address":r.ip_address,"created_at":r.created_at} for r in rows]
