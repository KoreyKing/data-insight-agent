"""时间戳契约（architecture.md §2.4）：UTC 生成、UTCDateTime 存储、存量报告偏移推断与换算。"""
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import Dataset
from app.modules.analysis_loop import run_analysis_loop
from app.modules.dataset_store import DatasetMaterializationError
from app.modules.history_context import build_history_context, select_previous_report
from app.modules.reporting import default_structured_task, generate_traceable_report
from app.modules.sample_data import load_retail_sample
from app.timestamps import (
    as_utc,
    generation_offset,
    infer_offset,
    isoformat_utc,
    normalize_report_times,
    report_ran_at,
    utc_now_iso,
)

SHANGHAI = timezone(timedelta(hours=8))
TIME_RANGE = {
    "current_start": "2026-05-11",
    "current_end": "2026-05-17",
    "previous_start": "2026-05-04",
    "previous_end": "2026-05-10",
}


def legacy_report(
    report_id: str,
    *,
    ran_at: datetime,
    created_at: datetime,
    metadata_ran_at: str | None,
    evidence_ran_at: str | None = None,
    previous_comparison: dict | None = None,
) -> SimpleNamespace:
    metadata: dict = {"model": "deepseek-flash", "time_range": dict(TIME_RANGE)}
    if metadata_ran_at is not None:
        metadata["ran_at"] = metadata_ran_at
    report_json: dict = {"status": "completed", "summary": f"{report_id} summary", "kpis": []}
    report_json["metadata"] = metadata
    if evidence_ran_at is not None:
        report_json["findings"] = [
            {
                "id": "finding-1",
                "type": "trend",
                "text": "结论",
                "evidence": {"sql": "SELECT 1", "ran_at": evidence_ran_at, "iteration": 3},
            }
        ]
    if previous_comparison is not None:
        report_json["previous_comparison"] = previous_comparison
    return SimpleNamespace(
        id=report_id,
        ran_at=ran_at,
        created_at=created_at,
        status="completed",
        summary=f"{report_id} summary",
        report_json=report_json,
    )


def local_legacy_report() -> SimpleNamespace:
    """本地 dev（Asia/Shanghai）生成的存量报告：payload 与 ran_at 列都是 +8 墙上时间。"""
    return legacy_report(
        "legacy-local",
        ran_at=datetime(2026, 9, 15, 17, 52, 33),
        created_at=datetime(2026, 9, 15, 9, 52, 33, 648970),
        metadata_ran_at="2026-09-15T17:52:33",
        evidence_ran_at="2026-09-15T17:52:10",
    )


def docker_legacy_report(previous_ran_at: str = "2026-09-15T17:52:33") -> SimpleNamespace:
    """Docker（容器 UTC）生成的存量重跑报告：上期时间抄自本地报告的 ran_at 列。"""
    return legacy_report(
        "legacy-docker",
        ran_at=datetime(2026, 9, 21, 11, 46, 52),
        created_at=datetime(2026, 9, 21, 11, 46, 52, 201528),
        metadata_ran_at="2026-09-21T11:46:52",
        evidence_ran_at="2026-09-21T11:46:30",
        previous_comparison={
            "previous_report_id": "legacy-local",
            "previous_ran_at": previous_ran_at,
            "previous_status": "completed",
            "previous_time_range": dict(TIME_RANGE),
            "same_period": False,
            "baseline": [],
            "summary_note": "legacy-local summary",
        },
    )


requires_tzset = pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="time.tzset 仅在类 Unix 系统可用"
)


def assert_recent_utc(stamp: str) -> None:
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None, stamp
    assert parsed.utcoffset() == timedelta(0), stamp
    assert abs(datetime.now(UTC) - parsed) < timedelta(seconds=5), stamp


@pytest.fixture
def shanghai_process_timezone():
    """把进程时区切到 Asia/Shanghai（本地 dev 的真实情况），结束后恢复。"""
    original = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    try:
        assert time.localtime().tm_gmtoff == 8 * 3600
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


# ------------------------------------------------------------------ 基础换算
def test_as_utc_reads_naive_as_utc_and_converts_aware_values():
    naive = datetime(2026, 9, 21, 11, 46, 52)
    assert as_utc(naive) == datetime(2026, 9, 21, 11, 46, 52, tzinfo=UTC)
    converted = as_utc(datetime(2026, 9, 21, 19, 46, 52, tzinfo=SHANGHAI))
    assert converted == datetime(2026, 9, 21, 11, 46, 52, tzinfo=UTC)
    assert converted.utcoffset() == timedelta(0)


def test_isoformat_utc_always_carries_an_explicit_offset():
    assert isoformat_utc(None) is None
    assert isoformat_utc(datetime(2026, 9, 21, 12, 23, 0, 891052)) == (
        "2026-09-21T12:23:00.891052+00:00"
    )
    assert isoformat_utc(datetime(2026, 9, 21, 19, 46, 52, tzinfo=SHANGHAI)) == (
        "2026-09-21T11:46:52+00:00"
    )
    assert isoformat_utc(datetime(2026, 9, 21, 12, 23, 0, 891052), timespec="seconds") == (
        "2026-09-21T12:23:00+00:00"
    )


def test_utc_now_iso_is_second_precision_utc():
    stamp = utc_now_iso()
    assert stamp.endswith("+00:00")
    assert datetime.fromisoformat(stamp).microsecond == 0
    assert_recent_utc(stamp)


# ------------------------------------------------------------------ 存量偏移推断
@pytest.mark.parametrize(
    ("local_wall", "utc_anchor", "expected"),
    [
        # 本地 dev（+8）生成的存量报告的真实取值
        (datetime(2026, 9, 15, 17, 52, 33), datetime(2026, 9, 15, 9, 52, 33, 648970), 8 * 60),
        # Docker（UTC）生成的存量报告的真实取值
        (datetime(2026, 6, 2, 12, 20, 20), datetime(2026, 6, 2, 12, 20, 20, 231374), 0),
        # 西半球（夏令时 / 冬令时各按生成当时的偏移）与非整点时区
        (datetime(2026, 9, 15, 5, 52, 33), datetime(2026, 9, 15, 9, 52, 33, 600000), -4 * 60),
        (datetime(2026, 1, 15, 4, 52, 33), datetime(2026, 1, 15, 9, 52, 33, 600000), -5 * 60),
        (datetime(2026, 9, 15, 15, 37, 33), datetime(2026, 9, 15, 9, 52, 33, 600000), 5 * 60 + 45),
        # 边界：±14 小时可接受；残差恰为 5 分钟可接受
        (datetime(2026, 9, 15, 23, 52, 33), datetime(2026, 9, 15, 9, 52, 33), 14 * 60),
        (datetime(2026, 9, 14, 19, 52, 33), datetime(2026, 9, 15, 9, 52, 33), -14 * 60),
        (datetime(2026, 9, 15, 17, 57, 33), datetime(2026, 9, 15, 9, 52, 33), 8 * 60),
        # 读库得到的是被标成 UTC 的本地墙上时间，结果相同
        (
            datetime(2026, 9, 15, 17, 52, 33, tzinfo=UTC),
            datetime(2026, 9, 15, 9, 52, 33, 648970, tzinfo=UTC),
            8 * 60,
        ),
        # 取整残差 7 分钟 > 5 分钟：不是同一次运行的打点，无法推断
        (datetime(2026, 9, 15, 17, 59, 33), datetime(2026, 9, 15, 9, 52, 33), 0),
        # 超出 ±14 小时（14:15、相差两天）：无法推断
        (datetime(2026, 9, 16, 0, 7, 33), datetime(2026, 9, 15, 9, 52, 33), 0),
        (datetime(2026, 9, 17, 9, 52, 33), datetime(2026, 9, 15, 9, 52, 33), 0),
    ],
)
def test_infer_offset_rounds_to_quarter_hours_with_guards(local_wall, utc_anchor, expected):
    assert infer_offset(local_wall, utc_anchor) == timedelta(minutes=expected)


def test_generation_offset_applies_only_to_reports_with_naive_metadata_ran_at():
    assert generation_offset(local_legacy_report()) == timedelta(hours=8)
    assert generation_offset(docker_legacy_report()) == timedelta(0)

    # 新报告：metadata.ran_at 带偏移，即使 ran_at 与 created_at 相差 8 小时（测试夹具）也不推断
    fresh = legacy_report(
        "fresh",
        ran_at=datetime(2026, 9, 15, 17, 52, 33, tzinfo=UTC),
        created_at=datetime(2026, 9, 15, 9, 52, 33, tzinfo=UTC),
        metadata_ran_at="2026-09-15T17:52:33+00:00",
    )
    assert generation_offset(fresh) == timedelta(0)

    # 缺失、非字符串、无法解析：旧写入路径此时落库的是当时的 UTC，按新报告处理
    for stamp in (None, 20260915, "yesterday"):
        odd = legacy_report(
            "odd",
            ran_at=datetime(2026, 9, 15, 17, 52, 33),
            created_at=datetime(2026, 9, 15, 9, 52, 33),
            metadata_ran_at=None,
        )
        if stamp is not None:
            odd.report_json["metadata"]["ran_at"] = stamp
        assert generation_offset(odd) == timedelta(0)


def test_report_ran_at_returns_the_true_utc_run_time():
    assert report_ran_at(local_legacy_report()) == datetime(2026, 9, 15, 9, 52, 33, tzinfo=UTC)
    assert report_ran_at(docker_legacy_report()) == datetime(2026, 9, 21, 11, 46, 52, tzinfo=UTC)

    as_read_from_db = local_legacy_report()
    as_read_from_db.ran_at = as_read_from_db.ran_at.replace(tzinfo=UTC)
    as_read_from_db.created_at = as_read_from_db.created_at.replace(tzinfo=UTC)
    assert report_ran_at(as_read_from_db) == datetime(2026, 9, 15, 9, 52, 33, tzinfo=UTC)

    fresh = legacy_report(
        "fresh",
        ran_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 22, 12, 0, 0, 400000, tzinfo=UTC),
        metadata_ran_at="2026-09-22T12:00:00+00:00",
    )
    assert report_ran_at(fresh) == datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    assert report_ran_at(SimpleNamespace(ran_at=None)) is None


# ------------------------------------------------------------------ payload 换算
def test_normalize_report_times_converts_a_legacy_local_payload():
    report = local_legacy_report()
    payload = deepcopy(report.report_json)

    normalize_report_times(payload, report)

    assert payload["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"
    assert payload["findings"][0]["evidence"]["ran_at"] == "2026-09-15T09:52:10+00:00"
    assert payload["metadata"]["time_range"] == TIME_RANGE


def test_normalize_report_times_takes_previous_run_time_from_the_referenced_report():
    report = docker_legacy_report()
    payload = deepcopy(report.report_json)

    normalize_report_times(payload, report, local_legacy_report())

    assert payload["metadata"]["ran_at"] == "2026-09-21T11:46:52+00:00"
    assert payload["findings"][0]["evidence"]["ran_at"] == "2026-09-21T11:46:30+00:00"
    # 上期出自 +8 进程：不能按本报告（UTC 进程）的偏移换算
    assert payload["previous_comparison"]["previous_ran_at"] == "2026-09-15T09:52:33+00:00"
    assert payload["previous_comparison"]["previous_time_range"] == TIME_RANGE


def test_normalize_report_times_falls_back_to_own_offset_without_previous_report():
    report = docker_legacy_report()
    payload = deepcopy(report.report_json)

    normalize_report_times(payload, report, None)

    assert payload["previous_comparison"]["previous_ran_at"] == "2026-09-15T17:52:33+00:00"


def test_normalize_report_times_brings_other_offsets_to_utc():
    report = legacy_report(
        "offsets",
        ran_at=datetime(2026, 9, 15, 9, 52, 33, tzinfo=UTC),
        created_at=datetime(2026, 9, 15, 9, 52, 33, 400000, tzinfo=UTC),
        metadata_ran_at="2026-09-15T09:52:33Z",
        evidence_ran_at="2026-09-15T17:52:10+08:00",
    )
    payload = deepcopy(report.report_json)

    normalize_report_times(payload, report)

    assert payload["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"
    assert payload["findings"][0]["evidence"]["ran_at"] == "2026-09-15T09:52:10+00:00"


def test_normalize_report_times_tolerates_malformed_findings():
    report = local_legacy_report()
    for findings in (1, True, {"id": "x"}, ["not-a-dict", {"evidence": "not-a-dict"}]):
        payload = deepcopy(report.report_json)
        payload["findings"] = findings
        normalize_report_times(payload, report)
        assert payload["findings"] == findings
        assert payload["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"


def test_column_and_payload_offsets_are_inferred_independently():
    # 假设 ran_at 列被单独改写成了 UTC、payload 未动：两侧仍各自换算正确
    report = local_legacy_report()
    report.ran_at = datetime(2026, 9, 15, 9, 52, 33)
    payload = deepcopy(report.report_json)

    normalize_report_times(payload, report)

    assert report_ran_at(report) == datetime(2026, 9, 15, 9, 52, 33, tzinfo=UTC)
    assert payload["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"
    assert payload["findings"][0]["evidence"]["ran_at"] == "2026-09-15T09:52:10+00:00"


def test_normalize_report_times_leaves_new_payloads_and_unparseable_values_alone():
    fresh = legacy_report(
        "fresh",
        ran_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 22, 12, 0, 0, 400000, tzinfo=UTC),
        metadata_ran_at="2026-09-22T12:00:00+00:00",
        evidence_ran_at="2026-09-22T11:59:40+00:00",
        previous_comparison={
            "previous_report_id": "x",
            "previous_ran_at": "2026-09-15T09:52:33+00:00",
        },
    )
    payload = deepcopy(fresh.report_json)
    normalize_report_times(payload, fresh, local_legacy_report())
    assert payload == fresh.report_json

    broken = local_legacy_report()
    broken.report_json["findings"][0]["evidence"]["ran_at"] = ""
    payload = deepcopy(broken.report_json)
    normalize_report_times(payload, broken)
    assert payload["findings"][0]["evidence"]["ran_at"] == ""
    assert payload["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"


# ------------------------------------------------------------------ 先后顺序与上期
def test_previous_report_selection_uses_true_run_time_across_the_upgrade():
    # 升级前 18:00（+8）生成的本地报告：原始列比升级后 12:00 UTC 的新报告「更晚」，实际更早
    legacy = legacy_report(
        "legacy-evening",
        ran_at=datetime(2026, 9, 22, 18, 0),
        created_at=datetime(2026, 9, 22, 10, 0, 0, 500000),
        metadata_ran_at="2026-09-22T18:00:00",
    )
    fresh = legacy_report(
        "fresh-noon-utc",
        ran_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 22, 12, 0, 0, 400000, tzinfo=UTC),
        metadata_ran_at="2026-09-22T12:00:00+00:00",
    )

    assert select_previous_report([legacy, fresh]) is fresh
    assert select_previous_report([fresh, legacy]) is fresh


def test_history_context_previous_ran_at_is_the_true_utc_run_time():
    context = build_history_context(local_legacy_report())

    assert context["previous_ran_at"] == "2026-09-15T09:52:33+00:00"


# ------------------------------------------------------------------ UTCDateTime 列
def test_utc_datetime_columns_store_utc_and_read_back_aware():
    init_db()
    engine = get_engine()
    with SessionLocal(bind=engine) as session:
        dataset = Dataset(
            created_at=datetime(2026, 9, 21, 19, 46, 52, tzinfo=SHANGHAI),
            data_source_ref_json={"id": "d", "type": "csv", "name": "d.csv", "location": "d.csv"},
            schema_summary_json={"columns": []},
            preview_json={"head": [], "tail": []},
            field_profile_json={"is_valid": True},
            file_path="d.csv",
            file_name="d.csv",
            row_count=1,
            column_count=1,
        )
        session.add(dataset)
        session.commit()
        dataset_id = dataset.id

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT created_at FROM datasets WHERE id = :id"), {"id": dataset_id}
        ).scalar_one()
        # 存量行的写法：SQLAlchemy 默认格式、无时区
        connection.execute(
            text("UPDATE datasets SET created_at = '2026-06-02 12:20:20.229031' WHERE id = :id"),
            {"id": dataset_id},
        )
        connection.commit()
    assert stored == "2026-09-21 11:46:52.000000"

    with SessionLocal(bind=engine) as session:
        read_back = session.get(Dataset, dataset_id).created_at
    assert read_back == datetime(2026, 6, 2, 12, 20, 20, 229031, tzinfo=UTC)
    assert read_back.utcoffset() == timedelta(0)


def test_utc_datetime_columns_reject_naive_values():
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        session.add(
            Dataset(
                created_at=datetime(2026, 9, 21, 19, 46, 52),
                data_source_ref_json={"id": "d", "type": "csv", "name": "d.csv"},
                schema_summary_json={"columns": []},
                preview_json={"head": [], "tail": []},
                field_profile_json={"is_valid": True},
                file_path="d.csv",
                file_name="d.csv",
                row_count=1,
                column_count=1,
            )
        )
        with pytest.raises(StatementError, match="UTCDateTime"):
            session.commit()


# ------------------------------------------------------------------ 进程时区无关
@requires_tzset
def test_experience_report_timestamps_do_not_depend_on_process_timezone(
    shanghai_process_timezone,
):
    report = generate_traceable_report(load_retail_sample(), "帮我生成周度经营复盘")

    assert_recent_utc(report["metadata"]["ran_at"])
    assert report["findings"]
    for finding in report["findings"]:
        assert_recent_utc(finding["evidence"]["ran_at"])


class ScriptedLLMClient:
    def __init__(self, responses: list[dict]):
        self.responses = [json.dumps(response, ensure_ascii=False) for response in responses]

    def complete(self, messages: list[dict[str, str]]) -> str:
        return self.responses.pop(0)


def loop_task() -> dict:
    table = load_retail_sample()
    return default_structured_task("帮我生成周度经营复盘", asdict(table.data_source_ref))


@requires_tzset
def test_analysis_loop_timestamps_do_not_depend_on_process_timezone(shanghai_process_timezone):
    llm = ScriptedLLMClient(
        [
            {
                "tool": "query_data",
                "args": {"sql": "SELECT store_name, SUM(net_sales_amount) AS sales "
                         "FROM sales_orders GROUP BY store_name ORDER BY sales DESC LIMIT 3"},
            },
            {
                "tool": "record_finding",
                "args": {"type": "trend", "text": "头部门店贡献销售额。", "evidence": "query-1"},
            },
            {
                "tool": "record_finding",
                "args": {"type": "recommendation", "text": "复核口径。", "evidence": "口径说明"},
            },
            {"tool": "finish", "args": {"summary": "完成"}},
        ]
    )

    report = run_analysis_loop(load_retail_sample(), loop_task(), llm)

    assert report["status"] == "completed"
    assert_recent_utc(report["metadata"]["ran_at"])
    assert [finding["evidence"]["evidence_ref"] for finding in report["findings"]] == [
        "query-1",
        "口径说明",
    ]
    for finding in report["findings"]:
        assert_recent_utc(finding["evidence"]["ran_at"])


@requires_tzset
def test_failed_analysis_loop_timestamp_does_not_depend_on_process_timezone(
    shanghai_process_timezone,
    monkeypatch,
):
    def fail_materialization(_table, **_kwargs):
        raise DatasetMaterializationError("CSV_KEY_FIELD_MISSING", "缺少关键字段")

    monkeypatch.setattr(
        "app.modules.analysis_loop.materialize_table_to_sqlite",
        fail_materialization,
    )

    report = run_analysis_loop(load_retail_sample(), loop_task(), ScriptedLLMClient([]))

    assert report["status"] == "failed"
    assert_recent_utc(report["metadata"]["ran_at"])
