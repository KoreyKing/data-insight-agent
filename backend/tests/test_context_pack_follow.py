"""未编辑的活动包跟随出厂口径（architecture.md §6.4 v0.18）与出厂内容 ↔ 版本号的钉住。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import ContextPackRecord
from app.main import app
from app.modules.context_pack import (
    builtin_base_version,
    builtin_pack_name,
    comparable_payload,
    load_default_context_pack,
    matches_factory,
    stamped_payload,
)
from app.modules.persistence import (
    ensure_seeded_context_pack,
    follow_factory_if_unedited,
    save_context_pack,
)

# 每个已发布出厂版本的内容摘要，按版本号递增只追加、不改写已有项。出厂内容变化须提升
# meta.version（§6.4）：改了内置 JSON 却没提升版本号，或提升了版本号却没登记新摘要，这里都会变红。
FACTORY_DIGESTS = {
    "1.0.0": "e9ccdbf0afbf48cfa8aed957caa960e24d5d49eb93becf2ff23dcd7067f6255b",
    "1.0.2": "2b1c8fe64134b23ee19ee2c1a75665fefc3c4d58d413f11b091d0eb159d6d6ae",
}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def factory_digest() -> str:
    payload = comparable_payload(load_default_context_pack())
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def active_record() -> ContextPackRecord:
    with SessionLocal(bind=get_engine()) as session:
        return session.scalars(
            select(ContextPackRecord).where(ContextPackRecord.name == builtin_pack_name())
        ).one()


def older_factory_pack() -> dict:
    """模拟上一版出厂内容：库存周转的说明还是旧文案。"""
    pack = deepcopy(load_default_context_pack())
    inventory = next(metric for metric in pack["metrics"] if metric["name"] == "库存周转")
    inventory["notes"] = "旧版样例数据未覆盖库存字段，遇到库存类问题需降级说明。"
    return pack


def store_record(payload: dict, *, base_version: str, revision: int) -> None:
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        session.add(
            ContextPackRecord(
                name=builtin_pack_name(),
                base_version=base_version,
                revision=revision,
                payload_json=stamped_payload(payload, base_version),
            )
        )
        session.commit()


def test_factory_content_change_requires_a_version_bump():
    versions = list(FACTORY_DIGESTS)

    assert versions == sorted(versions, key=version_key), "登记表须按版本号递增追加"
    assert len(set(FACTORY_DIGESTS.values())) == len(versions), "每个版本号对应一份不同的出厂内容"
    assert builtin_base_version() == versions[-1], "当前出厂版本须登记为最后一项"
    assert factory_digest() == FACTORY_DIGESTS[versions[-1]], (
        "出厂口径内容变化须同时提升 meta.version，并在本文件登记新版本的摘要"
    )


def test_unedited_pack_follows_factory_content_and_version_on_startup():
    store_record(older_factory_pack(), base_version="1.0.0", revision=0)

    ensure_seeded_context_pack()

    record = active_record()
    assert (record.base_version, record.revision) == (builtin_base_version(), 0)
    assert matches_factory(record.payload_json)
    assert record.payload_json["meta"]["version"] == builtin_base_version()
    with TestClient(app) as client:
        body = client.get("/api/v1/context-pack").json()
    assert (body["version"], body["revision"], body["is_modified"]) == (
        builtin_base_version(),
        0,
        False,
    )


def test_unedited_pack_with_current_content_only_takes_the_new_version_label():
    store_record(load_default_context_pack(), base_version="1.0.0", revision=0)

    ensure_seeded_context_pack()

    record = active_record()
    assert (record.base_version, record.revision) == (builtin_base_version(), 0)
    assert record.payload_json["meta"]["version"] == builtin_base_version()
    assert comparable_payload(record.payload_json) == comparable_payload(
        load_default_context_pack()
    )


def test_follow_is_idempotent_once_the_pack_matches_the_factory():
    store_record(older_factory_pack(), base_version="1.0.0", revision=0)
    ensure_seeded_context_pack()
    first = active_record()

    ensure_seeded_context_pack()

    second = active_record()
    assert (second.base_version, second.revision) == (first.base_version, first.revision)
    assert second.payload_json == first.payload_json
    assert second.updated_at == first.updated_at


def test_saved_pack_is_never_overwritten_by_the_factory():
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        edited = older_factory_pack()
        save_context_pack(session, edited)
        session.commit()
    before = active_record()

    ensure_seeded_context_pack()

    after = active_record()
    assert (after.base_version, after.revision) == (before.base_version, before.revision)
    assert after.payload_json == before.payload_json
    assert not matches_factory(after.payload_json)


def test_follow_leaves_a_save_that_lands_first_untouched():
    store_record(older_factory_pack(), base_version="1.0.0", revision=0)
    with SessionLocal(bind=get_engine()) as session:
        stale = session.scalars(select(ContextPackRecord)).one()
        with SessionLocal(bind=get_engine()) as other:
            save_context_pack(other, older_factory_pack())
            other.commit()

        assert follow_factory_if_unedited(session, stale) is False
        session.commit()

    after = active_record()
    assert after.revision == 1
    assert not matches_factory(after.payload_json)
