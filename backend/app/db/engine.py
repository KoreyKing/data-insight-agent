from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False)

_engine_cache: dict[str, Engine] = {}
PROJECT_ROOT = Path(__file__).resolve().parents[3]

SQLITE_COLUMN_UPGRADES = {
    "reports": {
        "task_id": "VARCHAR(36) REFERENCES analysis_tasks(id)",
    },
}


def normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("APP_DB_URL must use SQLite (the only supported application database)")
    database_path = url.database
    if not database_path or database_path == ":memory:":
        return database_url
    path = Path(database_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return url.set(database=str(path.resolve())).render_as_string(hide_password=False)


def get_engine(database_url: str | None = None) -> Engine:
    resolved_url = normalize_database_url(database_url or get_settings().app_db_url)
    if resolved_url not in _engine_cache:
        ensure_sqlite_parent_dir(resolved_url)
        kwargs = {"future": True, "connect_args": {"check_same_thread": False}}
        _engine_cache[resolved_url] = create_engine(resolved_url, **kwargs)
    return _engine_cache[resolved_url]


def init_db(database_url: str | None = None) -> None:
    from app.db import models as _models  # noqa: F401

    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    ensure_columns(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_parent_dir(database_url: str) -> None:
    url = make_url(database_url)
    database_path = url.database
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def ensure_columns(engine: Engine) -> None:
    """Apply the allowlisted SQLite column upgrades needed by supported old databases."""
    if engine.dialect.name != "sqlite":
        raise ValueError("APP_DB_URL must use SQLite (the only supported application database)")

    with engine.begin() as connection:
        for table_name, columns in SQLITE_COLUMN_UPGRADES.items():
            existing_columns = {
                row["name"]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})").mappings()
            }
            for column_name, definition in columns.items():
                if column_name not in existing_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                    )
            if table_name == "reports" and "task_id" in columns:
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_reports_task_id ON reports (task_id)"
                )
