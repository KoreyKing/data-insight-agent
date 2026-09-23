"""时刻的唯一出口（architecture.md §2.4）。

后端产生的时刻一律取 UTC，与进程所在时区无关；对外统一输出带 `+00:00` 的 ISO 串。

存量报告（v0.16 之前）的 payload 时刻与 `reports.ran_at` 列都是生成进程的本地时间且不带时区。
同一次运行里紧随其后写入、恒为 UTC 的 `created_at` 可以推断出生成进程的偏移：只在读取时换算，
不迁移数据。列与 payload 各按自身的值推断（存量数据中两者相同），
任何一侧被单独改写都不会连累另一侧。
报告相关函数只依赖鸭子类型（ran_at / created_at / report_json），不 import ORM。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

OFFSET_STEP = timedelta(minutes=15)
MAX_OFFSET = timedelta(hours=14)
MAX_RESIDUAL = timedelta(minutes=5)
NO_OFFSET = timedelta(0)
EARLIEST = datetime.min.replace(tzinfo=UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """报告 payload 内的时刻：UTC、精确到秒，如 `2026-09-21T11:46:52+00:00`。"""
    return utc_now().isoformat(timespec="seconds")


def as_utc(value: datetime) -> datetime:
    """无时区值按 UTC 解释（应用库约定）；带时区值换算到 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_utc(value: datetime | None, *, timespec: str = "auto") -> str | None:
    return as_utc(value).isoformat(timespec=timespec) if value is not None else None


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def infer_offset(local_wall: datetime, utc_anchor: datetime) -> timedelta:
    """同一时刻的本地墙上时间 − UTC 锚点，按 15 分钟取整；残差或范围越界视为无法推断（0）。"""
    difference = local_wall.replace(tzinfo=None) - as_utc(utc_anchor).replace(tzinfo=None)
    offset = OFFSET_STEP * round(difference / OFFSET_STEP)
    if abs(offset) > MAX_OFFSET or abs(difference - offset) > MAX_RESIDUAL:
        return NO_OFFSET
    return offset


def generation_offset(report: Any) -> timedelta:
    """存量报告 ran_at 列的生成进程偏移；新报告为 0。

    metadata.ran_at 为无偏移串即存量报告；带偏移、缺失、非字符串或无法解析都按新报告处理，
    ran_at 列即 UTC——旧版写入路径在后三种情况下落库的正是当时的 UTC 时刻。
    """
    if _legacy_stamp(report) is None:
        return NO_OFFSET
    return _offset_from(getattr(report, "ran_at", None), report)


def report_ran_at(report: Any) -> datetime | None:
    """报告的运行时刻（aware UTC）：新报告即 ran_at 列，存量报告减去生成进程偏移。"""
    ran_at = getattr(report, "ran_at", None)
    if not isinstance(ran_at, datetime):
        return None
    return _shift(ran_at, generation_offset(report))


def report_order_key(report: Any) -> tuple[datetime, datetime, str]:
    """报告先后（§2.4 第 6 条）：运行时刻，并列按 created_at、id。"""
    created_at = getattr(report, "created_at", None)
    return (
        report_ran_at(report) or EARLIEST,
        as_utc(created_at) if isinstance(created_at, datetime) else EARLIEST,
        str(getattr(report, "id", "") or ""),
    )


def normalize_report_times(
    payload: dict[str, Any],
    report: Any,
    previous_report: Any | None = None,
) -> dict[str, Any]:
    """把 payload 时刻统一为 `+00:00`（就地修改调用方的副本）：存量无偏移值按生成进程偏移换算。

    上期时间出自上期报告的生成进程，优先取所指报告换算后的运行时刻，缺失时按本报告偏移换算。
    """
    offset = _offset_from(_legacy_stamp(report), report)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        _convert_field(metadata, "ran_at", offset)
    findings = payload.get("findings")
    for finding in findings if isinstance(findings, list) else []:
        evidence = finding.get("evidence") if isinstance(finding, dict) else None
        if isinstance(evidence, dict):
            _convert_field(evidence, "ran_at", offset)
    comparison = payload.get("previous_comparison")
    if isinstance(comparison, dict):
        previous_ran_at = report_ran_at(previous_report) if previous_report is not None else None
        if previous_ran_at is not None and _is_naive_stamp(comparison.get("previous_ran_at")):
            comparison["previous_ran_at"] = isoformat_utc(previous_ran_at, timespec="seconds")
        else:
            _convert_field(comparison, "previous_ran_at", offset)
    return payload


def _legacy_stamp(report: Any) -> datetime | None:
    """存量报告的 metadata.ran_at（无偏移的生成进程本地时间）；新报告返回 None。"""
    report_json = getattr(report, "report_json", None)
    metadata = report_json.get("metadata") if isinstance(report_json, dict) else None
    stamp = parse_iso(metadata.get("ran_at")) if isinstance(metadata, dict) else None
    return stamp if stamp is not None and stamp.tzinfo is None else None


def _offset_from(local_wall: Any, report: Any) -> timedelta:
    created_at = getattr(report, "created_at", None)
    if not isinstance(local_wall, datetime) or not isinstance(created_at, datetime):
        return NO_OFFSET
    return infer_offset(local_wall, created_at)


def _shift(value: datetime, offset: timedelta) -> datetime:
    if offset == NO_OFFSET:
        return as_utc(value)
    return (value.replace(tzinfo=None) - offset).replace(tzinfo=UTC)


def _is_naive_stamp(value: Any) -> bool:
    parsed = parse_iso(value)
    return parsed is not None and parsed.tzinfo is None


def _convert_field(container: dict[str, Any], key: str, offset: timedelta) -> None:
    """无偏移值按偏移换算；带偏移的值只统一为 `+00:00`；无法解析的值原样保留。"""
    parsed = parse_iso(container.get(key))
    if parsed is None:
        return
    converted = as_utc(parsed) if parsed.tzinfo is not None else _shift(parsed, offset)
    container[key] = isoformat_utc(converted, timespec="seconds")
