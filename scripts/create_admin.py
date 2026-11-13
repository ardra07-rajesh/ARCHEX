"""Create or promote an ARCHEX administrator without exposing a public signup role."""
import getpass, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.database.session import SessionLocal, init_db
from app.database.models import User
from app.core.security import hash_password


def main():
    init_db()
    email = input("Admin email: ").strip().lower()
    name = input("Display name: ").strip() or "ARCHEX Administrator"
    password = getpass.getpass("Password (12+ chars, upper/lower/digit): ")
    if len(password) < 12 or not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        raise SystemExit("Password does not meet the minimum policy")
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role = "admin"; user.is_active = True; user.password_hash = hash_password(password); user.updated_at = now
        else:
            user = User(id=str(uuid.uuid4()), email=email, display_name=name, password_hash=hash_password(password),
                        role="admin", is_active=True, created_at=now, updated_at=now)
            db.add(user)
        db.commit()
    print(f"Administrator ready: {email}")

if __name__ == "__main__": main()
