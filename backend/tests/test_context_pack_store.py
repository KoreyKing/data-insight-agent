"""活动 Context Pack 的存储 / 种子 / 版本语义 / 读取回落（architecture.md §6.4）。"""
from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import ContextPackRecord
from app.main import app
from app.modules.context_pack import (
    builtin_pack_name,
    effective_version,
    load_active_context_pack,
    load_default_context_pack,
    stamped_payload,
)
from app.modules.context_pack_validation import validate_context_pack_edit
from app.modules.field_mapping import build_field_profile
from app.modules.file_ingestion import build_schema_summary
from app.modules.persistence import (
    reset_context_pack,
    save_context_pack,
    seed_context_pack,
)


def active_record() -> ContextPackRecord | None:
    with SessionLocal(bind=get_engine()) as session:
        return session.scalars(
            select(ContextPackRecord).where(ContextPackRecord.name == builtin_pack_name())
        ).one_or_none()


def chinese_header_schema(pack: dict[str, Any] | None = None):
    """以内置包各列 display_name 作表头的合成 schema（§6.4 dry-run / §7 capture 口径）。"""
    columns = (pack or load_default_context_pack())["data_dictionary"]["tables"][0]["columns"]
    row = {
        column["display_name"]: (
            "2026-05-11"
            if column["name"] == "order_date"
            else 1000
            if column["data_type"] in {"decimal", "integer"}
            else "示例值"
        )
        for column in columns
    }
    return build_schema_summary(pd.DataFrame([row]))


def canonical_fields(profile) -> set[str]:
    return {mapping.canonical_field for mapping in profile.mappings.values()}


def test_effective_version_switches_to_local_suffix_after_first_save():
    assert effective_version("1.0.0", 0) == "1.0.0"
    assert effective_version("1.0.0", 1) == "1.0.0-local.1"
    assert effective_version("1.0.0", 12) == "1.0.0-local.12"


def test_app_startup_seeds_active_pack_once_and_is_idempotent():
    with TestClient(app):
        first = active_record()
        assert first is not None
        seeded_id, created_at = first.id, first.created_at
        assert first.revision == 0
        assert first.base_version == load_default_context_pack()["meta"]["version"]
        assert first.payload_json["meta"]["version"] == first.base_version
        assert first.payload_json["metrics"] == load_default_context_pack()["metrics"]

    with TestClient(app):
        second = active_record()

    assert second is not None
    assert (second.id, second.created_at, second.revision) == (seeded_id, created_at, 0)
    with SessionLocal(bind=get_engine()) as session:
        assert len(session.scalars(select(ContextPackRecord)).all()) == 1


def test_load_active_pack_falls_back_to_builtin_without_table_or_record():
    # 表不存在（库从未初始化）→ 回落内置，不抛异常
    assert load_active_context_pack()["meta"] == load_default_context_pack()["meta"]

    init_db()
    # 表已建但无记录 → 同样回落内置
    assert load_active_context_pack()["meta"] == load_default_context_pack()["meta"]


def test_load_active_pack_reads_stored_payload_with_computed_version():
    init_db()
    edited = deepcopy(load_default_context_pack())
    columns = edited["data_dictionary"]["tables"][0]["columns"]
    for column in columns:
        if column["name"] == "channel":
            column["aliases"] = [*column["aliases"], "投放渠道"]
    edited["meta"]["version"] = "9.9.9-ignored"

    with SessionLocal(bind=get_engine()) as session:
        save_context_pack(session, edited)
        session.commit()

    active = load_active_context_pack()

    assert active["meta"]["version"] == "1.0.0-local.1"
    channel = next(
        column
        for column in active["data_dictionary"]["tables"][0]["columns"]
        if column["name"] == "channel"
    )
    assert "投放渠道" in channel["aliases"]


def test_load_active_pack_falls_back_when_stored_payload_is_invalid(caplog):
    init_db()
    broken = deepcopy(load_default_context_pack())
    broken["metrics"] = [metric for metric in broken["metrics"] if metric["name"] != "销售额"]
    with SessionLocal(bind=get_engine()) as session:
        record = seed_context_pack(session)
        record.payload_json = stamped_payload(broken, "1.0.0-local.1")
        record.revision = 1
        session.commit()

    with caplog.at_level(logging.WARNING, logger="app.modules.context_pack"):
        active = load_active_context_pack()

    assert {metric["name"] for metric in active["metrics"]} >= {"销售额"}
    assert active["meta"]["version"] == "1.0.0"
    assert "CONTEXT_PACK_NOT_FOUND" in caplog.text


def test_save_and_reset_keep_revision_monotonic_and_restore_builtin_content():
    init_db()
    edited = deepcopy(load_default_context_pack())
    edited["report_preferences"]["anomaly_thresholds"]["significant_pct"] = 12.5

    with SessionLocal(bind=get_engine()) as session:
        saved = save_context_pack(session, edited)
        session.commit()
        assert saved.revision == 1
        assert saved.payload_json["meta"]["version"] == "1.0.0-local.1"

        restored = reset_context_pack(session)
        session.commit()

    assert restored.revision == 2
    assert restored.payload_json["meta"]["version"] == "1.0.0-local.2"
    assert restored.payload_json["report_preferences"] == (
        load_default_context_pack()["report_preferences"]
    )
    assert load_active_context_pack()["report_preferences"]["anomaly_thresholds"] == {
        "significant_pct": 10.0,
        "critical_pct": 30.0,
    }


def test_builtin_pack_recognizes_display_name_headers_including_channel():
    profile = build_field_profile(chinese_header_schema(), load_default_context_pack())

    assert profile.is_valid is True
    assert {"order_date", "net_sales_amount", "channel"} <= canonical_fields(profile)


def test_removing_column_aliases_stops_recognition_without_fallback_revival():
    """别名权威（§6.4）：删掉列别名后，内置回退表不得把该列救回来。"""
    edited = deepcopy(load_default_context_pack())
    for column in edited["data_dictionary"]["tables"][0]["columns"]:
        if column["name"] == "channel":
            column["aliases"] = ["投放渠道"]

    schema = chinese_header_schema()
    before = canonical_fields(build_field_profile(schema, load_default_context_pack()))
    after = canonical_fields(build_field_profile(schema, edited))

    assert "channel" in before
    assert "channel" not in after
    assert {"order_date", "net_sales_amount"} <= after


def test_field_profile_defaults_to_active_pack_after_edit():
    init_db()
    edited = deepcopy(load_default_context_pack())
    for column in edited["data_dictionary"]["tables"][0]["columns"]:
        if column["name"] == "channel":
            column["aliases"] = ["投放渠道"]
    with SessionLocal(bind=get_engine()) as session:
        save_context_pack(session, edited)
        session.commit()

    profile = build_field_profile(chinese_header_schema())

    assert "channel" not in canonical_fields(profile)
    assert profile.is_valid is True


@pytest.mark.parametrize("endpoint", ["/api/v1/sample-dataset"])
def test_upload_and_report_responses_carry_active_pack_version(endpoint: str, tmp_path: Path):
    with TestClient(app) as client:
        factory = client.get(endpoint)
        assert factory.status_code == 200
        assert factory.json()["context_pack_version"] == "1.0.0"

        edited = deepcopy(load_default_context_pack())
        edited["report_preferences"]["anomaly_thresholds"]["significant_pct"] = 12.5
        with SessionLocal(bind=get_engine()) as session:
            save_context_pack(session, edited)
            session.commit()

        after_edit = client.get(endpoint)
        report = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘"},
        )

    assert after_edit.json()["context_pack_version"] == "1.0.0-local.1"
    assert report.status_code == 200
    assert report.json()["report"]["context_pack_version"] == "1.0.0-local.1"
    assert str(tmp_path) not in report.text


# ---------------------------------------------------------------- 编辑 API
def mutated(mutate) -> dict[str, Any]:
    pack = load_default_context_pack()
    mutate(pack)
    return pack


def column_by_name(pack: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        column
        for column in pack["data_dictionary"]["tables"][0]["columns"]
        if column["name"] == name
    )


def metric_by_name(pack: dict[str, Any], name: str) -> dict[str, Any]:
    return next(metric for metric in pack["metrics"] if metric["name"] == name)


def test_builtin_pack_passes_all_four_validation_layers():
    validation = validate_context_pack_edit(load_default_context_pack())

    assert validation.errors == []
    assert validation.warnings == []


def test_get_context_pack_seeds_and_returns_factory_state():
    with TestClient(app) as client:
        response = client.get("/api/v1/context-pack")

    body = response.json()
    assert response.status_code == 200
    assert body["name"] == builtin_pack_name()
    assert (body["version"], body["revision"], body["is_modified"]) == ("1.0.0", 0, False)
    assert body["updated_at"]
    assert body["payload"]["metrics"] == load_default_context_pack()["metrics"]
    assert active_record() is not None


def test_put_alias_edit_bumps_revision_and_changes_field_recognition():
    edited = mutated(lambda pack: column_by_name(pack, "channel").update(aliases=["投放渠道"]))

    with TestClient(app) as client:
        before = client.get("/api/v1/sample-dataset").json()["context_pack_version"]
        response = client.put("/api/v1/context-pack", json=edited)
        after = client.get("/api/v1/context-pack").json()

    body = response.json()
    assert response.status_code == 200
    assert (body["version"], body["revision"], body["is_modified"]) == ("1.0.0-local.1", 1, True)
    assert body["warnings"] == []
    assert column_by_name(body["payload"], "channel")["aliases"] == ["投放渠道"]
    assert before == "1.0.0"
    assert after["version"] == "1.0.0-local.1"
    assert "channel" not in canonical_fields(
        build_field_profile(chinese_header_schema(), after["payload"])
    )


def test_put_accepts_wrapped_payload_and_overrides_server_managed_fields():
    edited = mutated(lambda pack: column_by_name(pack, "channel").update(aliases=["投放渠道"]))
    edited["meta"]["version"] = "9.9.9"
    edited["history_context"] = {"last_run_summary": "注入内容", "baseline_values": {"销售额": 1}}

    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json={"payload": edited})

    body = response.json()
    assert response.status_code == 200
    assert body["version"] == "1.0.0-local.1"
    assert body["payload"]["meta"]["version"] == "1.0.0-local.1"
    assert body["payload"]["history_context"] == load_default_context_pack()["history_context"]


def test_put_reference_layer_warning_saves_with_readable_hint():
    edited = mutated(
        lambda pack: metric_by_name(pack, "客单价").update(calculation="销售额 / 订单总数")
    )

    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json=edited)

    body = response.json()
    assert response.status_code == 200
    assert body["revision"] == 1
    assert [warning["layer"] for warning in body["warnings"]] == [3]
    assert "订单总数" in body["warnings"][0]["message"]


def test_put_prompt_size_warning_saves_with_budget_hint():
    edited = mutated(lambda pack: metric_by_name(pack, "销售额").update(notes="运" * 7000))

    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json=edited)

    body = response.json()
    assert response.status_code == 200
    assert body["revision"] == 1
    assert any(warning["layer"] == 4 for warning in body["warnings"])
    assert any("提前收尾" in warning["message"] for warning in body["warnings"])


def drop_required_metric(pack: dict[str, Any]) -> None:
    pack["metrics"] = [metric for metric in pack["metrics"] if metric["name"] != "销售额"]


def add_conflicting_alias(pack: dict[str, Any]) -> None:
    column_by_name(pack, "category_l1")["aliases"].append("销售渠道")


def move_net_sales_alias_to_discount(pack: dict[str, Any]) -> None:
    net_sales = column_by_name(pack, "net_sales_amount")
    net_sales["aliases"] = [alias for alias in net_sales["aliases"] if alias != "净销售额"]
    column_by_name(pack, "discount_amount")["aliases"].append("净销售额")


@pytest.mark.parametrize(
    ("label", "mutate", "layer", "fragment"),
    [
        ("删除必需指标", drop_required_metric, 1, "销售额"),
        ("修改场景名", lambda pack: pack["meta"].update(name="Retail X"), 2, "不可修改"),
        ("别名冲突", add_conflicting_alias, 2, "销售渠道"),
        (
            "修改表名",
            lambda pack: pack["data_dictionary"]["tables"][0].update(name="orders"),
            2,
            "数据表名不可修改",
        ),
        (
            "修改显示名",
            lambda pack: column_by_name(pack, "channel").update(display_name="渠道"),
            2,
            "显示名不可修改",
        ),
        (
            "删除字段",
            lambda pack: pack["data_dictionary"]["tables"][0]["columns"].pop(),
            2,
            "字段不可增减",
        ),
        (
            "阈值倒置",
            lambda pack: pack["report_preferences"]["anomaly_thresholds"].update(
                significant_pct=40.0
            ),
            2,
            "标黄阈值必须小于标红阈值",
        ),
        (
            "阈值非正",
            lambda pack: pack["report_preferences"]["anomaly_thresholds"].update(
                significant_pct=-1.0
            ),
            2,
            "必须大于 0",
        ),
        (
            "非法规则等级",
            lambda pack: pack["validation_rules"][0].update(severity="fatal"),
            2,
            "error 或 warning",
        ),
        (
            "引用未知字段",
            lambda pack: metric_by_name(pack, "销售额").update(
                calculation="SUM(gross_amount) WHERE order_status = 'completed'"
            ),
            3,
            "gross_amount",
        ),
        (
            "口径过大",
            lambda pack: metric_by_name(pack, "销售额").update(notes="x" * 70000),
            4,
            "64 KB",
        ),
        ("别名改坏必需字段识别", move_net_sales_alias_to_discount, 4, "无法识别必需字段"),
    ],
)
def test_put_rejects_invalid_pack_without_partial_save(
    label: str,
    mutate,
    layer: int,
    fragment: str,
):
    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json=mutated(mutate))
        after = client.get("/api/v1/context-pack").json()

    body = response.json()
    errors = body["details"]["errors"]
    assert response.status_code == 400, label
    assert body["code"] == "CONTEXT_PACK_VALIDATION_FAILED"
    assert any(error["layer"] == layer and fragment in error["message"] for error in errors), (
        label,
        errors,
    )
    assert (after["revision"], after["is_modified"]) == (0, False)
    assert after["payload"] == load_default_context_pack()


def test_reset_restores_factory_content_and_keeps_revision_monotonic():
    edited = mutated(lambda pack: column_by_name(pack, "channel").update(aliases=["投放渠道"]))

    with TestClient(app) as client:
        saved = client.put("/api/v1/context-pack", json=edited).json()
        restored = client.post("/api/v1/context-pack/reset").json()
        sample = client.get("/api/v1/sample-dataset").json()

    assert (saved["revision"], saved["is_modified"]) == (1, True)
    assert (restored["revision"], restored["is_modified"]) == (2, False)
    assert restored["version"] == "1.0.0-local.2"
    assert column_by_name(restored["payload"], "channel")["aliases"] == (
        column_by_name(load_default_context_pack(), "channel")["aliases"]
    )
    assert sample["context_pack_version"] == "1.0.0-local.2"


def test_edited_pack_version_flows_into_upload_and_report_responses():
    edited = mutated(
        lambda pack: pack["report_preferences"]["anomaly_thresholds"].update(significant_pct=12.5)
    )

    with TestClient(app) as client:
        client.put("/api/v1/context-pack", json=edited)
        upload = client.post(
            "/api/v1/uploads",
            files={
                "file": (
                    "probe.csv",
                    "订单日期,净销售额,门店名称\n2026-05-11,1000,成都店\n".encode(),
                    "text/csv",
                )
            },
        )
        report = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘"},
        )
        parsed = client.post("/api/v1/tasks/parse", json={"analysis_goal": "看看销售"})

    assert upload.json()["context_pack_version"] == "1.0.0-local.1"
    assert report.json()["report"]["context_pack_version"] == "1.0.0-local.1"
    assert parsed.json()["task"]["context_pack_version"] == "1.0.0-local.1"


def test_legacy_p1_database_gains_context_pack_table_and_seed(tmp_path: Path, monkeypatch):
    from tests.test_persistence import create_p1_era_database

    database_path = tmp_path / "p1-legacy.db"
    database_url = f"sqlite:///{database_path}"
    create_p1_era_database(database_url)
    monkeypatch.setenv("APP_DB_URL", database_url)

    with TestClient(app) as client:
        pack = client.get("/api/v1/context-pack").json()
        reports = client.get("/api/v1/reports").json()

    assert (pack["version"], pack["revision"]) == ("1.0.0", 0)
    assert reports["total"] == 1


# ------------------------------------ 单次运行同源 / 文案业务化 / 时区（v0.13）
def count_active_pack_reads(monkeypatch) -> list[int]:
    """统计活动包的 DB 读取次数：一次运行只允许解析一次快照（§6.4 单次运行同源）。"""
    from app.modules import context_pack as context_pack_module

    calls: list[int] = []
    original = context_pack_module.read_active_context_pack_record

    def counting_read():
        calls.append(1)
        return original()

    monkeypatch.setattr(context_pack_module, "read_active_context_pack_record", counting_read)
    return calls


def upload_chinese_csv(client: TestClient, filename: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/uploads",
        files={
            "file": (
                filename,
                "订单日期,销售额,门店,类目,渠道\n2026-05-11,1000,成都店,童装,线下\n".encode(),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    return {"id": response.json()["session_id"], "type": "csv"}


def save_pack_without_channel_aliases() -> None:
    edited = mutated(lambda pack: column_by_name(pack, "channel").update(aliases=["投放渠道"]))
    with SessionLocal(bind=get_engine()) as session:
        save_context_pack(session, edited)
        session.commit()


def test_materialization_follows_the_run_snapshot_instead_of_rereading(tmp_path: Path):
    from app.modules.dataset_store import materialize_table_to_sqlite
    from app.modules.file_ingestion import load_table_from_path

    init_db()
    save_pack_without_channel_aliases()
    source = tmp_path / "zh.csv"
    source.write_text("订单日期,净销售额,销售渠道\n2026-05-11,1000,线下\n", encoding="utf-8")
    table = load_table_from_path(source)

    with_snapshot = materialize_table_to_sqlite(table, context_pack=load_default_context_pack())
    without_snapshot = materialize_table_to_sqlite(table)

    assert "channel" in {column.name for column in with_snapshot.schema_summary.columns}
    assert "channel" not in {column.name for column in without_snapshot.schema_summary.columns}


def test_report_run_reads_the_active_pack_once_including_materialization(monkeypatch):
    monkeypatch.setattr("app.modules.report_runner.get_llm_client", lambda _settings=None: None)
    with TestClient(app) as client:
        calls = count_active_pack_reads(monkeypatch)
        response = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘"},
        )

    assert response.status_code == 200
    assert len(calls) == 1


def test_rerun_keeps_one_pack_snapshot_when_the_pack_is_saved_mid_run(monkeypatch):
    """rerun 在指纹比对后、物化前发生口径保存：分析表仍按比对时的快照物化，版本与列集同源。"""
    import app.api.tasks as tasks_api
    import app.modules.reporting as reporting_module

    monkeypatch.setattr("app.modules.report_runner.get_llm_client", lambda _settings=None: None)
    materialized_columns: list[set[str]] = []
    original_materialize = reporting_module.materialize_table_to_sqlite

    def spying_materialize(table, **kwargs):
        handle = original_materialize(table, **kwargs)
        materialized_columns.append({column.name for column in handle.schema_summary.columns})
        return handle

    monkeypatch.setattr(reporting_module, "materialize_table_to_sqlite", spying_materialize)
    original_history = tasks_api.history_context_for_task

    def history_with_concurrent_edit(task):
        save_pack_without_channel_aliases()
        return original_history(task)

    with TestClient(app) as client:
        founding = upload_chinese_csv(client, "founding.csv")
        run = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘", "data_source_ref": founding},
        )
        task_id = client.post("/api/v1/tasks", json={"report_id": run.json()["report_id"]}).json()[
            "id"
        ]
        rerun_source = upload_chinese_csv(client, "rerun.csv")
        materialized_columns.clear()
        monkeypatch.setattr(tasks_api, "history_context_for_task", history_with_concurrent_edit)
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": rerun_source},
        )

    assert response.status_code == 200
    assert response.json()["report"]["context_pack_version"] == "1.0.0"
    assert materialized_columns and all("channel" in columns for columns in materialized_columns)


def test_rerun_reads_the_active_pack_once(monkeypatch):
    monkeypatch.setattr("app.modules.report_runner.get_llm_client", lambda _settings=None: None)
    with TestClient(app) as client:
        founding = upload_chinese_csv(client, "founding.csv")
        run = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘", "data_source_ref": founding},
        )
        task_id = client.post("/api/v1/tasks", json={"report_id": run.json()["report_id"]}).json()[
            "id"
        ]
        rerun_source = upload_chinese_csv(client, "rerun.csv")
        calls = count_active_pack_reads(monkeypatch)
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": rerun_source},
        )

    assert response.status_code == 200
    assert len(calls) == 1


def test_put_reports_emptied_core_aliases_per_field_in_business_terms():
    edited = mutated(lambda pack: column_by_name(pack, "channel").update(aliases=[]))
    channel_index = next(
        index
        for index, column in enumerate(edited["data_dictionary"]["tables"][0]["columns"])
        if column["name"] == "channel"
    )

    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json=edited)

    errors = response.json()["details"]["errors"]
    assert response.status_code == 400
    assert errors == [
        {
            "layer": 1,
            "path": f"data_dictionary.tables[0].columns[{channel_index}].aliases",
            "message": "字段「销售渠道」是核心分析字段，至少保留一个别名。",
        }
    ]


def test_alias_conflict_message_names_fields_by_display_name():
    validation = validate_context_pack_edit(mutated(add_conflicting_alias))

    conflict = [issue for issue in validation.errors if "同时" in issue.message]
    assert len(conflict) == 1
    assert "「商品类目」" in conflict[0].message
    assert "「销售渠道」" in conflict[0].message
    assert "category_l1" not in conflict[0].message
    assert "channel" not in conflict[0].message


def test_missing_required_metric_message_is_business_worded():
    validation = validate_context_pack_edit(mutated(drop_required_metric))

    assert [issue.as_dict() for issue in validation.errors if issue.layer == 1] == [
        {"layer": 1, "path": "metrics", "message": "必需指标「销售额」不可删除。"}
    ]


def test_context_pack_updated_at_is_timezone_aware_utc():
    from datetime import datetime, timedelta

    with TestClient(app) as client:
        factory = client.get("/api/v1/context-pack").json()
        saved = client.put(
            "/api/v1/context-pack",
            json=mutated(
                lambda pack: pack["report_preferences"]["anomaly_thresholds"].update(
                    significant_pct=12.0
                )
            ),
        ).json()

    for body in (factory, saved):
        parsed = datetime.fromisoformat(body["updated_at"])
        assert parsed.utcoffset() == timedelta(0)


def test_analysis_loop_run_reads_the_active_pack_once(monkeypatch):
    """真实模型路径（Analysis Loop）同样只解析一次快照：物化不得二次读取活动包。"""
    import json

    class FinishingLLM:
        def complete(self, _messages):
            return json.dumps({"tool": "finish", "args": {"summary": "口径同源探针。"}})

    monkeypatch.setattr(
        "app.modules.report_runner.get_llm_client",
        lambda _settings=None: FinishingLLM(),
    )
    with TestClient(app) as client:
        calls = count_active_pack_reads(monkeypatch)
        response = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘"},
        )

    assert response.status_code == 200
    assert response.json()["report"]["metadata"]["loop_rounds"] == 1
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("指标名为列表", lambda pack: pack["metrics"][0].update(name=["销售额"])),
        ("指标名为对象", lambda pack: pack["metrics"][0].update(name={"text": "销售额"})),
        ("字段名为列表", lambda pack: column_by_name(pack, "channel").update(name=["channel"])),
        (
            "指标名为列表且渠道别名清空",
            lambda pack: (
                pack["metrics"][0].update(name=["销售额"]),
                column_by_name(pack, "channel").update(aliases=[]),
            ),
        ),
    ],
)
def test_put_rejects_malformed_names_with_validation_error_not_crash(label: str, mutate):
    with TestClient(app) as client:
        response = client.put("/api/v1/context-pack", json=mutated(mutate))

    assert response.status_code == 400, label
    assert response.json()["code"] == "CONTEXT_PACK_VALIDATION_FAILED", label


def test_structure_layer_keeps_reporting_other_structural_errors():
    """业务化的逐字段报错不能吞掉其余结构错误（§2.3：details.errors 列全量）。"""

    def mutate(pack: dict[str, Any]) -> None:
        pack.pop("analysis_templates")
        column_by_name(pack, "channel").update(aliases=[])

    validation = validate_context_pack_edit(mutated(mutate))
    layer_one = [issue.message for issue in validation.errors if issue.layer == 1]

    assert "字段「销售渠道」是核心分析字段，至少保留一个别名。" in layer_one
    assert any(
        message.startswith("业务口径结构不完整") and "analysis_templates" in message
        for message in layer_one
    ), layer_one
