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


def get_engine(database_url: str | None = None) -> Engine:
    resolved_url = database_url or get_settings().app_db_url
    if resolved_url not in _engine_cache:
        ensure_sqlite_parent_dir(resolved_url)
        kwargs = {"future": True}
        if make_url(resolved_url).get_backend_name() == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine_cache[resolved_url] = create_engine(resolved_url, **kwargs)
    return _engine_cache[resolved_url]


def init_db(database_url: str | None = None) -> None:
    from app.db import models as _models  # noqa: F401

    Base.metadata.create_all(bind=get_engine(database_url))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_parent_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    database_path = url.database
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
