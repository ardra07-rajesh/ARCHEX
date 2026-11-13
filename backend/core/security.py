"""Small dependency-free token and password primitives for ARCHEX."""
import base64, hashlib, hmac, json, os, secrets, time
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from sqlalchemy import select
from app.config import settings
from app.database.models import User
from app.database.session import SessionLocal

_ITERATIONS = 310_000

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${_b64(salt)}${_b64(digest)}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(rounds))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False

def create_access_token(user: User) -> tuple[str, int]:
    secret = settings.auth_secret
    if not secret:
        raise RuntimeError("ARCHEX_AUTH_SECRET must be configured to issue access tokens")
    now = int(time.time()); expires = now + settings.auth_token_minutes * 60
    header = _b64(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub":user.id,"role":user.role,"iat":now,"exp":expires}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}"
    signature = _b64(hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest())
    return f"{signing}.{signature}", expires

def decode_access_token(token: str) -> dict | None:
    try:
        header, payload, signature = token.split(".")
        header_data = json.loads(_unb64(header))
        if header_data.get("alg") != "HS256" or header_data.get("typ") != "JWT": return None
        signing = f"{header}.{payload}"
        expected = _b64(hmac.new(settings.auth_secret.encode(), signing.encode(), hashlib.sha256).digest())
        if not settings.auth_secret or not hmac.compare_digest(signature, expected): return None
        claims = json.loads(_unb64(payload))
        if int(claims.get("exp", 0)) <= int(time.time()) or not claims.get("sub"): return None
        return claims
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

def authenticate_request(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "): return None
    claims = decode_access_token(header[7:].strip())
    if not claims: return None
    with SessionLocal() as db:
        user = db.get(User, claims["sub"])
        if user is None or not user.is_active: return None
        # Return a detached lightweight identity; request handlers use its scalar fields.
        db.expunge(user)
        return user

def current_user(request: Request) -> User | None:
    return getattr(request.state, "current_user", None)

def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, detail={"code":"authentication_required","message":"Sign in to access this resource","errors":[]}, headers={"WWW-Authenticate":"Bearer"})
    return user

def enforce_owner(row, user: User | None):
    if user is not None and row.owner_id != user.id:
        raise HTTPException(404, detail={"code":"not_found","message":"Resource not found","errors":[]})
    return row

def audit(user_id: str | None, action: str, resource_type: str = "", resource_id: str = "", ip: str = "") -> None:
    from app.database.models import SecurityAuditEvent
    with SessionLocal() as db:
        db.add(SecurityAuditEvent(user_id=user_id, action=action, resource_type=resource_type,
                                  resource_id=resource_id, ip_address=ip[:64],
                                  created_at=datetime.now(timezone.utc).isoformat()))
        db.commit()
