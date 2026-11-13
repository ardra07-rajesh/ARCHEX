from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi import Request

from app.config import settings

_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def check_database() -> tuple[bool, str]:
    """Real connectivity probe (SELECT 1)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, engine.dialect.name
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"


def init_db() -> None:
    from app.database.models import Base

    Base.metadata.create_all(engine)


def get_db(request: Request):
    db = SessionLocal()
    user = getattr(request.state, "current_user", None)
    db.info["user_id"] = user.id if user is not None else None
    db.info["user_role"] = user.role if user is not None else None
    try:
        yield db
    finally:
        db.close()
