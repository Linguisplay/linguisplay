from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# check_same_thread only applies to SQLite; harmless to pass conditionally.
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_tune(dbapi_conn, _record):
        # WAL: 读写不再互斥 (双人并发回合撞 database is locked 直接崩, 台账 P2);
        # busy_timeout: 真撞锁时等 5s 而不是立刻炸; NORMAL 是 WAL 的标配持久档
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

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


def _column_default_sql(col) -> str:
    """把模型声明的默认值翻成 ADD COLUMN 的 DEFAULT 子句 (翻不动就不给默认值)。
    没有默认值的新列对已有行是 NULL —— 应用侧到处是 `or {}` / `or []` 兜得住,
    但像 runs.archived 这种会进 WHERE 的必须带上默认值, 否则老行被查询漏掉。"""
    import json as _json

    d = getattr(col, "default", None)
    if d is None:
        return ""
    v = None
    if getattr(d, "is_scalar", False):
        v = d.arg
    elif getattr(d, "is_callable", False):
        try:
            v = d.arg(None)
        except Exception:
            return ""
    if isinstance(v, bool):
        return f" DEFAULT {int(v)}"
    if isinstance(v, (int, float)):
        return f" DEFAULT {v}"
    if isinstance(v, str):
        return " DEFAULT '" + v.replace("'", "''") + "'"
    if isinstance(v, (list, dict)):
        return " DEFAULT '" + _json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    return ""


def _ensure_columns() -> None:
    """SQLite 加列差分器: create_all 从不给【已有表】加列, 所以照着模型声明补齐。

    这里曾经是一份手抄的列清单 (实弹 2026-08-04: `stories.creatures` 和 `factions`
    从来没被抄进去 → 本地 dev.db 一跑 smoke_stories.py 就 OperationalError, 而冒烟门
    正是部署前必过的那道门)。手抄清单的失效方式是沉默的: 加字段的人不知道还有一处要改。
    改成差分之后, 模型是唯一真源。

    只做【加列】—— 改名/删列/改类型仍然要人工介入, 那天就是上 Alembic 的日子。"""
    import sys

    from sqlalchemy import inspect, text
    from . import models  # noqa: F401  ensure models are registered

    insp = inspect(engine)
    insp.clear_cache()          # 别吃上一次 inspect 的缓存 (create_all 刚建过表)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            if not existing:
                # 读不出列 = 我们并不知道这张表现在长什么样。此时【什么都不做】才是对的:
                # 当成「一列都没有」会去 ALTER ADD 每一列(含主键), 全部报错只留下半截状态。
                print(f"[schema] cannot read columns of {table.name}, skipped", file=sys.stderr)
                continue
            for col in table.columns:
                if col.name in existing or col.primary_key:
                    continue
                try:
                    decl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(
                        f"ALTER TABLE {table.name} ADD COLUMN "
                        f"{col.name} {decl}{_column_default_sql(col)}"))
                except Exception as e:      # 不许静默: 补不上要喊, 否则又是一次沉默漂移
                    print(f"[schema] cannot add {table.name}.{col.name}: {e}",
                          file=sys.stderr)
