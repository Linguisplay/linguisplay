from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# check_same_thread only applies to SQLite; harmless to pass conditionally.
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # M1: create_all is enough. Switch to Alembic before M2 (pgvector columns).
    from . import models  # noqa: F401  ensure models are registered

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Tiny additive migration for SQLite (create_all never adds columns to existing
    tables). Add new nullable/defaulted columns here until we adopt Alembic."""
    from sqlalchemy import inspect, text

    wanted = {"stories": [("endings", "JSON DEFAULT '[]'"), ("world_facts", "TEXT"),
                          ("locations", "JSON DEFAULT '[]'"), ("mature", "INTEGER DEFAULT 0")],
              "beats": [("present_ids", "JSON")]}
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, decl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
