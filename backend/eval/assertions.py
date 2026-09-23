from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from math import isclose
from typing import Any

from app.modules.dataset_store import materialize_table_to_sqlite
from app.modules.query_engine import run_validated_query
from app.modules.schemas import TableData

KPI_KEYS = {
    "销售额": "sales_amount",
    "订单数": "order_count",
    "客单价": "average_order_value",
    "退款率": "refund_rate",
}


RATE_KPIS = {"退款率"}
PREVIOUS_REFERENCE_KEYWORDS = ("上期", "上一期", "上周", "上次", "连续", "较上期", "前一期")
LOCAL_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+-local\.[1-9]\d*$")
CHANNEL_VALUES = ("抖音", "天猫", "小程序", "线下")


def evaluate_report(
    report: dict[str, Any],
    table: TableData,
    qa: dict[str, Any],
    *,
    rerun: dict[str, Any] | None = None,
    capture: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """rerun 非 None 时追加四条 previous_comparison 硬断言与上期引用观察项。

    capture 非 None 时（§7 v0.13）：追加三条 capture 专属断言，预埋异常命中降为观察项；
    context_pack 为该用例运行时的口径快照，SQL 重放按同一快照物化（§6.4 单次运行同源）。
    """
    anomaly_coverage = check_anomaly_coverage(report, qa)
    hard_assertions = [
        check_status_completed(report),
        check_kpi_values(report, qa),
        check_finding_sql(report, table, context_pack=context_pack),
    ]
    if capture is None:
        hard_assertions.append(anomaly_coverage)
    hard_assertions.append(check_count_invariants(report))
    key_values: dict[str, Any] = {
        "kpis": extract_report_kpis(report),
        "matched_anomalies": anomaly_coverage["actual"]["matched_ids"],
    }
    observations = build_observations(report, anomaly_coverage)
    if capture is not None:
        hard_assertions.extend(
            [
                check_capture_field_unrecognized(capture),
                check_capture_version_traced(report, capture),
                check_capture_control(capture),
            ]
        )
        key_values["capture"] = capture
        observations["anomaly_coverage"] = anomaly_coverage["actual"]
        observations["capture_narrative_signal"] = capture_narrative_signal(report)
    if rerun is not None:
        hard_assertions.extend(
            [
                check_previous_comparison_present(report),
                check_previous_report_resolvable(report, rerun),
                check_previous_comparison_delta_math(report, qa),
                check_same_period_false(report),
            ]
        )
        key_values["previous_comparison"] = extract_previous_comparison(report)
        observations["previous_reference_signal"] = previous_reference_signal(report)
    return {
        "passed": hard_assertions_passed(hard_assertions),
        "hard_assertions": hard_assertions,
        "key_values": key_values,
        "observations": observations,
    }


def check_status_completed(report: dict[str, Any]) -> dict[str, Any]:
    actual = report.get("status")
    return assertion_result(
        "status_completed",
        actual == "completed",
        expected="completed",
        actual=actual,
        details="" if actual == "completed" else f"报告状态为 {actual!r}",
    )


def check_kpi_values(report: dict[str, Any], qa: dict[str, Any]) -> dict[str, Any]:
    actual = extract_report_kpis(report)
    expected: dict[str, dict[str, float | int]] = {}
    mismatches: list[str] = []
    qa_kpis = qa.get("core_kpis") if isinstance(qa, dict) else None
    qa_kpis = qa_kpis if isinstance(qa_kpis, dict) else {}

    for display_name, qa_key in KPI_KEYS.items():
        expected[display_name] = {}
        actual_kpi = actual.get(display_name, {})
        for window_name in ("current", "previous"):
            window = qa_kpis.get(window_name)
            expected_value = window.get(qa_key) if isinstance(window, dict) else None
            expected[display_name][window_name] = expected_value
            actual_value = actual_kpi.get(window_name)
            if not numeric_values_match(actual_value, expected_value):
                mismatches.append(
                    f"{display_name}.{window_name}: expected={expected_value!r}, "
                    f"actual={actual_value!r}"
                )

    return assertion_result(
        "kpi_values_match",
        not mismatches,
        expected=expected,
        actual=actual,
        details="; ".join(mismatches),
    )


def check_finding_sql(
    report: dict[str, Any],
    table: TableData,
    *,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    replay_failures: list[dict[str, str]] = []
    evidence_diagnostics: list[dict[str, Any]] = []
    empty_sql = 0
    replayed = 0
    handle = materialize_table_to_sqlite(table, context_pack=context_pack)
    try:
        for index, finding in enumerate(findings):
            evidence = finding.get("evidence") if isinstance(finding, dict) else None
            sql = evidence.get("sql") if isinstance(evidence, dict) else None
            evidence_ref = evidence.get("evidence_ref") if isinstance(evidence, dict) else None
            evidence_diagnostics.append(
                {
                    "finding": index + 1,
                    "text": str(finding.get("text") or "") if isinstance(finding, dict) else "",
                    "evidence_ref": evidence_ref,
                    "has_sql": isinstance(sql, str) and bool(sql.strip()),
                }
            )
            if not isinstance(sql, str) or not sql.strip():
                empty_sql += 1
                if is_query_evidence_ref(evidence_ref):
                    replay_failures.append(
                        {
                            "finding": str(index + 1),
                            "error": "query evidence 缺少可重放 SQL",
                        }
                    )
                continue
            try:
                run_validated_query(handle, sql)
                replayed += 1
            except Exception as exc:
                replay_failures.append(
                    {
                        "finding": str(index + 1),
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
    finally:
        handle.connection.close()

    empty_ratio = 1.0 if not findings else empty_sql / len(findings)
    passed = not replay_failures and empty_ratio <= 1 / 3
    actual = {
        "finding_count": len(findings),
        "replayed_sql_count": replayed,
        "empty_sql_count": empty_sql,
        "empty_sql_ratio": empty_ratio,
        "replay_failures": replay_failures,
        "evidence_diagnostics": evidence_diagnostics,
    }
    details: list[str] = []
    if empty_ratio > 1 / 3:
        details.append(f"空 SQL 占比 {empty_ratio:.3f} 超过 1/3")
    if replay_failures:
        details.append(f"{len(replay_failures)} 条 SQL 无法重放")
    return assertion_result(
        "finding_sql_replay",
        passed,
        expected={"empty_sql_ratio_max": 1 / 3, "replay_failures": []},
        actual=actual,
        details="; ".join(details),
    )


def check_anomaly_coverage(report: dict[str, Any], qa: dict[str, Any]) -> dict[str, Any]:
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    finding_text = "\n".join(
        str(finding.get("text") or "") for finding in findings if isinstance(finding, dict)
    ).casefold()
    entities = qa.get("anomaly_entities")
    entities = entities if isinstance(entities, list) else []
    matched_ids: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        keywords = entity.get("keywords")
        keywords = keywords if isinstance(keywords, list) else []
        if any(str(keyword).casefold() in finding_text for keyword in keywords if keyword):
            matched_ids.append(str(entity.get("id") or "unknown"))

    matched_count = len(matched_ids)
    return assertion_result(
        "anomaly_coverage",
        matched_count >= 2,
        expected={"minimum_matched": 2, "total": 3},
        actual={"matched_count": matched_count, "matched_ids": matched_ids},
        details="" if matched_count >= 2 else f"仅命中 {matched_count}/3 个预埋异常实体",
    )


def check_count_invariants(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    analysis_steps = report.get("analysis_steps")
    analysis_steps = analysis_steps if isinstance(analysis_steps, list) else []
    loop_rounds = metadata.get("loop_rounds")
    steps_recorded = metadata.get("steps_recorded")
    token_used = metadata.get("token_used")
    checks = {
        "loop_rounds_within_hard_limit": is_strict_int(loop_rounds)
        and 0 <= loop_rounds <= 15,
        "steps_recorded_matches_steps": is_strict_int(steps_recorded)
        and steps_recorded == len(analysis_steps),
        "token_used_positive": is_strict_int(token_used) and token_used > 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return assertion_result(
        "count_invariants",
        not failed,
        expected={
            "loop_rounds_max": 15,
            "steps_recorded": len(analysis_steps),
            "token_used_min": 1,
        },
        actual={
            "loop_rounds": loop_rounds,
            "steps_recorded": steps_recorded,
            "token_used": token_used,
            "analysis_steps_count": len(analysis_steps),
        },
        details=", ".join(failed),
    )


def capture_field_unrecognized_ok(
    recognized: Iterable[str],
    edited_fields: Iterable[str],
    required_fields: Iterable[str],
) -> bool:
    """编辑掉别名的字段不再被识别，且必需字段仍被识别（文件仍可分析，防空洞通过）。"""
    recognized_set = set(recognized)
    return not recognized_set & set(edited_fields) and set(required_fields) <= recognized_set


def capture_version_traced_ok(
    report_version: Any,
    stored_version: Any,
    edited_version: Any,
    pre_edit_version: Any,
) -> bool:
    """报告 payload 与落库版本都等于编辑保存返回的 -local.N 版本，且不同于编辑前版本。"""
    return (
        isinstance(edited_version, str)
        and LOCAL_VERSION_PATTERN.fullmatch(edited_version) is not None
        and report_version == edited_version
        and stored_version == edited_version
        and edited_version != pre_edit_version
    )


def check_capture_field_unrecognized(capture: dict[str, Any]) -> dict[str, Any]:
    stored = capture.get("report") if isinstance(capture.get("report"), dict) else None
    recognized = stored.get("recognized") if stored else None
    passed = isinstance(recognized, list) and capture_field_unrecognized_ok(
        recognized,
        capture.get("edited_fields", []),
        capture.get("required_fields", []),
    )
    details = ""
    if stored is None:
        details = "报告未落库，无法读取该次运行的字段识别"
    elif not passed:
        details = "落库数据集的字段识别仍含被编辑字段，或必需字段未识别"
    return assertion_result(
        "capture_field_unrecognized",
        passed,
        expected={
            "unrecognized": capture.get("edited_fields"),
            "still_recognized": capture.get("required_fields"),
        },
        actual={"recognized": recognized},
        details=details,
    )


def check_capture_version_traced(
    report: dict[str, Any],
    capture: dict[str, Any],
) -> dict[str, Any]:
    stored = capture.get("report") if isinstance(capture.get("report"), dict) else {}
    pre_edit = capture.get("pre_edit") if isinstance(capture.get("pre_edit"), dict) else {}
    actual = {
        "report_version": report.get("context_pack_version") if isinstance(report, dict) else None,
        "stored_version": stored.get("stored_version"),
        "edited_version": capture.get("edited_version"),
        "pre_edit_version": pre_edit.get("version"),
    }
    passed = capture_version_traced_ok(
        actual["report_version"],
        actual["stored_version"],
        actual["edited_version"],
        actual["pre_edit_version"],
    )
    return assertion_result(
        "capture_version_traced",
        passed,
        expected={"version": capture.get("edited_version"), "pattern": "{base}-local.{N}"},
        actual=actual,
        details="" if passed else "报告或落库记录的口径版本不是本次编辑保存的 -local.N 版本",
    )


def check_capture_control(capture: dict[str, Any]) -> dict[str, Any]:
    """内置红绿对照（§7 v0.13）：鉴别力必须来自正确原因。

    编辑前与恢复后两端都按出厂口径识别到被编辑字段与必需字段（字段断言因此判红）、
    都是出厂内容（is_modified 为 False）；恢复后版本不同于编辑版本与编辑前版本（revision 单调）。
    """
    edited_fields = set(capture.get("edited_fields") or [])
    required_fields = set(capture.get("required_fields") or [])
    pre_edit = capture.get("pre_edit") if isinstance(capture.get("pre_edit"), dict) else {}
    post_reset = capture.get("post_reset") if isinstance(capture.get("post_reset"), dict) else {}

    def factory_state(snapshot: dict[str, Any]) -> dict[str, Any]:
        recognized = set(snapshot.get("recognized") or [])
        return {
            "recognizes_edited_and_required": bool(edited_fields)
            and (edited_fields | required_fields) <= recognized,
            "is_modified": snapshot.get("is_modified"),
        }

    states = {"pre_edit": factory_state(pre_edit), "post_reset": factory_state(post_reset)}
    states["post_reset"]["version_advanced"] = post_reset.get("version") not in {
        capture.get("edited_version"),
        pre_edit.get("version"),
        None,
    }
    passed = all(
        state["recognizes_edited_and_required"] and state["is_modified"] is False
        for state in states.values()
    ) and states["post_reset"]["version_advanced"]
    return assertion_result(
        "capture_control",
        passed,
        expected={
            "pre_edit": {"recognizes_edited_and_required": True, "is_modified": False},
            "post_reset": {
                "recognizes_edited_and_required": True,
                "is_modified": False,
                "version_advanced": True,
            },
        },
        actual=states,
        details="" if passed else "编辑前或恢复后不是出厂识别 / 出厂内容，或版本未单调前进",
    )


def capture_narrative_signal(report: dict[str, Any]) -> dict[str, Any]:
    """观察项：编辑掉渠道别名后，叙事中是否仍出现渠道维度词与渠道取值。"""
    findings = report.get("findings") if isinstance(report, dict) else None
    findings = findings if isinstance(findings, list) else []
    text = "\n".join(
        [str(report.get("summary") or "") if isinstance(report, dict) else ""]
        + [str(finding.get("text") or "") for finding in findings if isinstance(finding, dict)]
    )
    return {
        "channel_dimension_mentioned": "渠道" in text,
        "channel_values_mentioned": [value for value in CHANNEL_VALUES if value in text],
    }


PREVIOUS_COMPARISON_KEYS = {
    "previous_report_id",
    "previous_ran_at",
    "previous_status",
    "previous_time_range",
    "same_period",
    "baseline",
    "summary_note",
}


def previous_comparison_section(report: dict[str, Any]) -> dict[str, Any] | None:
    section = report.get("previous_comparison") if isinstance(report, dict) else None
    return section if isinstance(section, dict) else None


def check_previous_comparison_present(report: dict[str, Any]) -> dict[str, Any]:
    section = previous_comparison_section(report)
    missing = sorted(PREVIOUS_COMPARISON_KEYS - set(section)) if section is not None else []
    baseline_is_list = section is not None and isinstance(section.get("baseline"), list)
    passed = section is not None and not missing and baseline_is_list
    details = ""
    if section is None:
        details = "报告缺少顶层 previous_comparison"
    elif missing:
        details = f"previous_comparison 缺少字段: {', '.join(missing)}"
    elif not baseline_is_list:
        details = "previous_comparison.baseline 不是列表"
    return assertion_result(
        "previous_comparison_present",
        passed,
        expected=sorted(PREVIOUS_COMPARISON_KEYS),
        actual=sorted(section) if section is not None else None,
        details=details,
    )


def check_previous_report_resolvable(
    report: dict[str, Any],
    rerun: dict[str, Any],
) -> dict[str, Any]:
    """previous_report_id 必须指向隔离库中 founding 报告且能查到。"""
    section = previous_comparison_section(report) or {}
    previous_report_id = section.get("previous_report_id")
    founding_report_id = rerun.get("founding_report_id")
    stored_ids = rerun.get("stored_report_ids")
    stored_ids = {str(item) for item in stored_ids} if isinstance(stored_ids, list) else set()
    is_founding = isinstance(previous_report_id, str) and previous_report_id == founding_report_id
    is_stored = isinstance(previous_report_id, str) and previous_report_id in stored_ids
    details: list[str] = []
    if not is_founding:
        details.append("previous_report_id 不等于 founding 报告 id")
    if not is_stored:
        details.append("previous_report_id 在隔离库中不存在")
    return assertion_result(
        "previous_report_resolvable",
        is_founding and is_stored,
        expected={"founding_report_id": founding_report_id, "stored": True},
        actual={"previous_report_id": previous_report_id, "stored": is_stored},
        details="; ".join(details),
    )


def check_previous_comparison_delta_math(
    report: dict[str, Any],
    qa: dict[str, Any],
) -> dict[str, Any]:
    """对比卡数值锚定期 2 QA 字面值：上期值 = QA previous、本期值 = QA current、delta 独立复算。"""
    section = previous_comparison_section(report) or {}
    baseline = section.get("baseline")
    entries = {
        item["name"]: item
        for item in (baseline if isinstance(baseline, list) else [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    qa_kpis = qa.get("core_kpis") if isinstance(qa, dict) else None
    qa_kpis = qa_kpis if isinstance(qa_kpis, dict) else {}
    qa_current = qa_kpis.get("current") if isinstance(qa_kpis.get("current"), dict) else {}
    qa_previous = qa_kpis.get("previous") if isinstance(qa_kpis.get("previous"), dict) else {}

    expected: dict[str, dict[str, Any]] = {}
    actual: dict[str, dict[str, Any] | None] = {}
    mismatches: list[str] = []
    for display_name, qa_key in KPI_KEYS.items():
        previous_value = qa_previous.get(qa_key)
        current_value = qa_current.get(qa_key)
        delta_unit = "pp" if display_name in RATE_KPIS else "%"
        expected_entry = {
            "previous_value": previous_value,
            "current_value": current_value,
            "delta_value": independent_delta(current_value, previous_value, delta_unit),
            "delta_unit": delta_unit,
        }
        expected[display_name] = expected_entry
        entry = entries.get(display_name)
        actual[display_name] = (
            {key: entry.get(key) for key in expected_entry} if entry is not None else None
        )
        if entry is None:
            mismatches.append(f"{display_name}: 对比卡缺少该指标")
            continue
        for key, expected_value in expected_entry.items():
            actual_value = entry.get(key)
            matched = (
                actual_value == expected_value
                if key == "delta_unit"
                else numeric_values_match(actual_value, expected_value)
            )
            if not matched:
                mismatches.append(
                    f"{display_name}.{key}: expected={expected_value!r}, actual={actual_value!r}"
                )

    return assertion_result(
        "previous_comparison_delta_math",
        not mismatches,
        expected=expected,
        actual=actual,
        details="; ".join(mismatches),
    )


def independent_delta(current: Any, previous: Any, delta_unit: str) -> float | None:
    """与产品实现无关的差值复算：pp 取差、% 取变化率；上期缺失或为 0 → None。"""
    if not is_number(current) or not is_number(previous):
        return None
    if delta_unit == "pp":
        return round(float(current) - float(previous), 2)
    if float(previous) == 0:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 2)


def check_same_period_false(report: dict[str, Any]) -> dict[str, Any]:
    section = previous_comparison_section(report) or {}
    actual = section.get("same_period")
    return assertion_result(
        "same_period_false",
        actual is False,
        expected=False,
        actual=actual,
        details="" if actual is False else f"same_period 为 {actual!r}，期 2 fixture 应为新时间窗",
    )


def previous_reference_signal(report: dict[str, Any]) -> dict[str, Any]:
    """观察项：分析正文 / finding 是否引用上期（关键词或基线数值）——「报告有记忆」的模型侧证据。"""
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    text = "\n".join(
        [str(report.get("summary") or "")]
        + [str(finding.get("text") or "") for finding in findings if isinstance(finding, dict)]
    )
    keywords = [keyword for keyword in PREVIOUS_REFERENCE_KEYWORDS if keyword in text]
    section = previous_comparison_section(report) or {}
    baseline = section.get("baseline")
    value_hits: list[str] = []
    for entry in baseline if isinstance(baseline, list) else []:
        if not isinstance(entry, dict) or not is_number(entry.get("previous_value")):
            continue
        if any(variant in text for variant in number_variants(float(entry["previous_value"]))):
            value_hits.append(str(entry.get("name")))
    return {
        "keywords_matched": keywords,
        "baseline_value_hits": value_hits,
        "any": bool(keywords or value_hits),
    }


def number_variants(value: float) -> set[str]:
    variants = {f"{value:.2f}", f"{value:,.2f}", f"{value:.1f}", f"{value:,.1f}"}
    if float(value).is_integer():
        variants |= {f"{int(value)}", f"{int(value):,}"}
    else:
        variants |= {f"{value:.0f}", f"{value:,.0f}"}
    return variants


def extract_previous_comparison(report: dict[str, Any]) -> dict[str, Any] | None:
    section = previous_comparison_section(report)
    if section is None:
        return None
    baseline = section.get("baseline")
    return {
        "previous_report_id": section.get("previous_report_id"),
        "previous_status": section.get("previous_status"),
        "same_period": section.get("same_period"),
        "baseline": [
            {
                key: entry.get(key)
                for key in (
                    "name",
                    "previous_value",
                    "current_value",
                    "delta_value",
                    "delta_unit",
                    "severity",
                )
            }
            for entry in (baseline if isinstance(baseline, list) else [])
            if isinstance(entry, dict)
        ],
    }


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def hard_assertions_passed(assertions: list[dict[str, Any]]) -> bool:
    return bool(assertions) and all(item.get("passed") is True for item in assertions)


def extract_report_kpis(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    kpis = report.get("kpis")
    kpis = kpis if isinstance(kpis, list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in kpis:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str):
            result[name] = {
                "current": item.get("current"),
                "previous": item.get("previous"),
                "unit": item.get("unit"),
            }
    return result


def build_observations(
    report: dict[str, Any],
    anomaly_assertion: dict[str, Any],
) -> dict[str, Any]:
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    metadata = report.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    distribution = Counter(
        str(finding.get("type") or "unknown")
        for finding in findings
        if isinstance(finding, dict)
    )
    return {
        "anomaly_full_hit": anomaly_assertion["actual"]["matched_count"] == 3,
        "finding_count": len(findings),
        "finding_type_distribution": dict(sorted(distribution.items())),
        "token_used": metadata.get("token_used"),
        "loop_rounds": metadata.get("loop_rounds"),
    }


def numeric_values_match(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual == expected
    if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return actual == expected
    return isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=0.01)


def is_query_evidence_ref(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("query-")


def is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def assertion_result(
    assertion_id: str,
    passed: bool,
    *,
    expected: Any,
    actual: Any,
    details: str,
) -> dict[str, Any]:
    return {
        "id": assertion_id,
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
        "details": details,
    }
