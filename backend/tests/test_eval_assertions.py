from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.context_pack import builtin_base_version, load_default_context_pack
from app.modules.file_ingestion import load_table_from_path
from app.modules.history_context import build_history_context
from app.modules.reporting import generate_traceable_report
from app.modules.sample_data import load_retail_sample
from eval.assertions import (
    check_anomaly_coverage,
    check_count_invariants,
    check_finding_sql,
    check_kpi_values,
    check_previous_comparison_delta_math,
    check_previous_comparison_present,
    check_previous_report_resolvable,
    check_same_period_false,
    evaluate_report,
    hard_assertions_passed,
    previous_reference_signal,
)
from eval.runner import (
    EvalSetupError,
    load_golden_questions,
    resolve_questions,
    run_question_with_retry,
    run_repeated_question,
    run_suite,
    temporary_eval_environment,
)
from eval.runner import (
    main as eval_main,
)

FACTORY_VERSION = builtin_base_version()

BACKEND_DIR = Path(__file__).resolve().parents[1]
PERIOD2_FIXTURE = BACKEND_DIR / "eval" / "fixtures" / "retail_sales_orders_period2.csv"


def load_period1_qa() -> dict:
    return json.loads((BACKEND_DIR / ".sample-data-qa.json").read_text(encoding="utf-8"))


def load_period2_qa() -> dict:
    return json.loads(PERIOD2_FIXTURE.with_suffix(".qa.json").read_text(encoding="utf-8"))


def test_product_kpis_match_independent_qa_literals():
    table = load_retail_sample()
    report = generate_traceable_report(table, "帮我生成周度经营复盘")

    result = check_kpi_values(report, load_period1_qa())

    assert result["passed"] is True
    assert result["actual"]["订单数"]["current"] == 1288
    assert result["actual"]["订单数"]["previous"] == 1236


def test_kpi_assertion_rejects_a_single_literal_mismatch():
    table = load_retail_sample()
    report = generate_traceable_report(table, "帮我生成周度经营复盘")
    report["kpis"][0]["current"] += 0.02

    result = check_kpi_values(report, load_period1_qa())

    assert result["passed"] is False
    assert "销售额.current" in result["details"]


def test_finding_sql_replay_passes_at_exact_empty_sql_boundary():
    report = {
        "findings": [
            finding_with_sql("SELECT COUNT(order_id) AS orders FROM sales_orders LIMIT 1;"),
            finding_with_sql(
                "SELECT store_name, SUM(net_sales_amount) AS sales "
                "FROM sales_orders GROUP BY store_name LIMIT 5;"
            ),
            finding_with_sql(""),
        ]
    }

    result = check_finding_sql(report, load_retail_sample())

    assert result["passed"] is True
    assert result["actual"]["empty_sql_ratio"] == 1 / 3
    assert result["actual"]["evidence_diagnostics"][0]["has_sql"] is True
    assert result["actual"]["evidence_diagnostics"][2]["evidence_ref"] == "short-note"


def test_finding_sql_replay_rejects_ratio_above_one_third():
    report = {
        "findings": [
            finding_with_sql("SELECT COUNT(order_id) AS orders FROM sales_orders LIMIT 1;"),
            finding_with_sql(""),
            finding_with_sql(""),
        ]
    }

    result = check_finding_sql(report, load_retail_sample())

    assert result["passed"] is False
    assert result["actual"]["empty_sql_ratio"] == 2 / 3


def test_finding_sql_replay_rejects_invalid_non_empty_sql():
    report = {"findings": [finding_with_sql("SELECT missing_column FROM sales_orders LIMIT 1;")]}

    result = check_finding_sql(report, load_retail_sample())

    assert result["passed"] is False
    assert result["actual"]["replay_failures"]


def test_finding_sql_replay_rejects_linked_query_without_sql():
    report = {
        "findings": [
            finding_with_sql("SELECT COUNT(order_id) AS orders FROM sales_orders LIMIT 1;"),
            finding_with_sql(
                "SELECT store_name, SUM(net_sales_amount) AS sales "
                "FROM sales_orders GROUP BY store_name LIMIT 5;"
            ),
            finding_with_sql("", evidence_ref="query-3"),
        ]
    }

    result = check_finding_sql(report, load_retail_sample())

    assert result["passed"] is False
    assert result["actual"]["empty_sql_ratio"] == 1 / 3
    assert result["actual"]["replay_failures"] == [
        {"finding": "3", "error": "query evidence 缺少可重放 SQL"}
    ]


def test_anomaly_coverage_matches_all_finding_types_and_requires_two_groups():
    qa = load_period1_qa()
    report = {
        "findings": [
            {"type": "trend", "text": "上海徐汇旗舰店销售额继续下降"},
            {"type": "recommendation", "text": "童装退款率需要优先处理"},
        ]
    }

    passing = check_anomaly_coverage(report, qa)
    failing_report = deepcopy(report)
    failing_report["findings"] = failing_report["findings"][:1]
    failing = check_anomaly_coverage(failing_report, qa)

    assert passing["passed"] is True
    assert passing["actual"]["matched_count"] == 2
    assert failing["passed"] is False
    assert failing["actual"]["matched_count"] == 1


def test_count_invariants_cover_loop_step_and_token_semantics():
    report = {
        "analysis_steps": [{"iteration": 1}, {"iteration": 2}],
        "metadata": {
            "loop_rounds": 3,
            "steps_recorded": 2,
            "token_used": 120,
        },
    }

    passing = check_count_invariants(report)
    too_many_rounds = check_count_invariants(
        {
            **report,
            "metadata": {**report["metadata"], "loop_rounds": 16},
        }
    )
    wrong_steps = check_count_invariants(
        {
            **report,
            "metadata": {**report["metadata"], "steps_recorded": 1},
        }
    )
    zero_tokens = check_count_invariants(
        {
            **report,
            "metadata": {**report["metadata"], "token_used": 0},
        }
    )
    boolean_counts = check_count_invariants(
        {
            **report,
            "analysis_steps": [{"iteration": 1}],
            "metadata": {
                **report["metadata"],
                "loop_rounds": True,
                "steps_recorded": True,
                "token_used": True,
            },
        }
    )

    assert passing["passed"] is True
    assert too_many_rounds["passed"] is False
    assert wrong_steps["passed"] is False
    assert zero_tokens["passed"] is False
    assert boolean_counts["passed"] is False


def test_hard_assertions_passed_requires_every_assertion_to_be_green():
    passing = [{"id": "one", "passed": True}, {"id": "two", "passed": True}]
    failing = [*passing, {"id": "three", "passed": False}]

    assert hard_assertions_passed(passing) is True
    assert hard_assertions_passed(failing) is False


def test_resolve_questions_accepts_short_q_number_selector():
    questions = [{"id": "q1_weekly_review"}, {"id": "q2_anomaly_diagnosis"}]

    selected = resolve_questions(questions, "q1")

    assert selected == [{"id": "q1_weekly_review"}]


def test_runner_retries_once_only_for_transient_llm_failure():
    calls = []
    outputs = [
        execution_output(passed=False, warning_code="LLM_CALL_FAILED"),
        execution_output(passed=True),
    ]

    def execute_once():
        calls.append("called")
        return outputs.pop(0)

    result = run_question_with_retry({"id": "q1_weekly_review"}, execute_once)

    assert len(calls) == 2
    assert result["attempts"] == 2
    assert result["passed"] is True


def test_runner_does_not_retry_deterministic_quality_failure():
    calls = []

    def execute_once():
        calls.append("called")
        return execution_output(passed=False)

    result = run_question_with_retry({"id": "q1_weekly_review"}, execute_once)

    assert len(calls) == 1
    assert result["attempts"] == 1
    assert result["passed"] is False


def test_repeat_requires_every_run_to_pass():
    outputs = [
        execution_output(passed=True),
        execution_output(passed=False),
    ]

    result = run_repeated_question(
        {"id": "q1_weekly_review"},
        repeat=2,
        execute_once=lambda: outputs.pop(0),
    )

    assert result["passed"] is False
    assert len(result["runs"]) == 2


def test_temporary_eval_environment_isolates_and_restores_runtime_paths(tmp_path: Path):
    from app.api import runtime

    original_db_url = os.environ.get("APP_DB_URL")
    original_data_dir = runtime.DATA_DIR
    original_upload_dir = runtime.UPLOAD_DIR
    original_sessions = runtime.UPLOAD_SESSIONS

    with temporary_eval_environment(base_dir=tmp_path) as environment:
        assert os.environ["APP_DB_URL"] == environment.database_url
        assert runtime.DATA_DIR == environment.data_dir
        assert runtime.UPLOAD_DIR == environment.upload_dir
        assert runtime.UPLOAD_SESSIONS == {}
        assert runtime.UPLOAD_SESSIONS is not original_sessions
        assert environment.database_path.parent == environment.data_dir
        assert environment.data_dir.parent == tmp_path

    assert os.environ.get("APP_DB_URL") == original_db_url
    assert runtime.DATA_DIR == original_data_dir
    assert runtime.UPLOAD_DIR == original_upload_dir
    assert runtime.UPLOAD_SESSIONS is original_sessions


def test_temporary_eval_environment_cleans_default_files_and_engine_cache():
    from app.db import engine as engine_module

    with temporary_eval_environment() as environment:
        environment.upload_dir.joinpath("probe.txt").write_text("probe", encoding="utf-8")
        engine = engine_module.get_engine(environment.database_url)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        root = environment.data_dir.parent
        database_url = environment.database_url
        normalized_database_url = engine_module.normalize_database_url(database_url)
        assert normalized_database_url in engine_module._engine_cache

    assert root.exists() is False
    assert normalized_database_url not in engine_module._engine_cache


def test_run_suite_reads_context_pack_identity_inside_isolation(monkeypatch):
    observed_database_urls: list[str | None] = []

    def isolated_identity():
        observed_database_urls.append(os.environ.get("APP_DB_URL"))
        return {
            "context_pack_name": "Retail Operations",
            "context_pack_version": "1.0.0",
        }

    monkeypatch.setattr("eval.runner.context_pack_identity", isolated_identity)
    monkeypatch.setattr(
        "eval.runner.run_repeated_question",
        lambda *_args, **_kwargs: {
            "id": "q1_weekly_review",
            "passed": True,
            "observations": {},
        },
    )

    suite = run_suite(
        [{"id": "q1_weekly_review"}],
        settings=SimpleNamespace(normalized_provider="test", llm_model="test-model"),
        llm_client=object(),
        repeat=1,
        only=None,
    )

    assert suite["passed"] is True
    assert len(observed_database_urls) == 1
    assert observed_database_urls[0]
    assert observed_database_urls[0].startswith("sqlite:////")


def test_eval_cli_returns_two_with_readable_message_when_llm_is_missing(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr("eval.runner.get_llm_client", lambda _settings: None)
    monkeypatch.setattr("eval.runner.get_settings", lambda: object())

    exit_code = eval_main([])

    assert exit_code == 2
    assert "未配置真实 LLM" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("failing_target", "error"),
    [
        ("eval.runner.get_settings", OSError(f"无法读取 {BACKEND_DIR}/private/config.json")),
        ("eval.runner.get_llm_client", ValueError("模型客户端参数无效")),
    ],
)
def test_eval_cli_maps_configuration_initialization_errors_to_exit_two(
    monkeypatch,
    capsys,
    failing_target,
    error,
):
    monkeypatch.setattr("eval.runner.get_settings", lambda: object())
    monkeypatch.setattr("eval.runner.get_llm_client", lambda _settings: object())
    monkeypatch.setattr(
        failing_target,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    exit_code = eval_main([])

    stderr = capsys.readouterr().err
    assert exit_code == 2
    assert "eval 设置失败" in stderr
    assert str(BACKEND_DIR) not in stderr


def test_eval_cli_rejects_baseline_update_with_repeat(monkeypatch, capsys):
    monkeypatch.setattr(
        "eval.runner.get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("不应读取配置")),
    )

    exit_code = eval_main(["--update-baseline", "--repeat", "2"])

    assert exit_code == 2
    assert "--update-baseline" in capsys.readouterr().err


def test_eval_cli_rejects_partial_baseline_update(monkeypatch, capsys):
    monkeypatch.setattr(
        "eval.runner.get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("不应读取配置")),
    )

    exit_code = eval_main(["--update-baseline", "--only", "q1"])

    assert exit_code == 2
    assert "--only" in capsys.readouterr().err


def finding_with_sql(sql: str, *, evidence_ref: str | None = None) -> dict:
    return {
        "type": "anomaly",
        "text": "测试 finding",
        "evidence": {
            "sql": sql,
            "evidence_ref": evidence_ref or ("query-1" if sql else "short-note"),
        },
    }


def execution_output(*, passed: bool, warning_code: str | None = None) -> dict:
    warnings = [] if warning_code is None else [{"code": warning_code}]
    return {
        "report": {"status": "completed" if passed else "partial", "warnings": warnings},
        "evaluation": {
            "passed": passed,
            "hard_assertions": [{"id": "status_completed", "passed": passed}],
            "key_values": {},
            "observations": {"token_used": 100},
        },
        "duration_seconds": 1.0,
    }


def period2_rerun_report() -> tuple[dict, dict]:
    """确定性全链：样例 founding（体验模式）→ history_context → 期 2 fixture 重跑（体验模式）。"""
    from datetime import UTC, datetime

    founding_table = load_retail_sample()
    founding_report = generate_traceable_report(founding_table, "帮我生成周度经营复盘")
    ran_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    previous = SimpleNamespace(
        id="r-founding",
        ran_at=ran_at,
        created_at=ran_at,
        status=founding_report["status"],
        summary=founding_report["summary"],
        report_json=founding_report,
    )
    history_context = build_history_context(previous)
    period2_table = load_table_from_path(
        PERIOD2_FIXTURE,
        original_filename=PERIOD2_FIXTURE.name,
        source_id="eval-test-period2",
    )
    report = generate_traceable_report(
        period2_table,
        "帮我生成周度经营复盘",
        history_context=history_context,
    )
    return report, history_context


def test_previous_comparison_delta_math_matches_period2_qa_literals():
    report, _history_context = period2_rerun_report()
    qa = load_period2_qa()

    result = check_previous_comparison_delta_math(report, qa)

    assert result["passed"] is True, result["details"]
    by_name = {entry["name"]: entry for entry in report["previous_comparison"]["baseline"]}
    current = qa["core_kpis"]["current"]
    previous = qa["core_kpis"]["previous"]
    expected_sales_delta = round(
        (current["sales_amount"] - previous["sales_amount"]) / previous["sales_amount"] * 100, 2
    )
    assert by_name["销售额"]["previous_value"] == previous["sales_amount"] == 390037.19
    assert by_name["销售额"]["current_value"] == current["sales_amount"] == 327985.38
    assert by_name["销售额"]["delta_value"] == expected_sales_delta == -15.91
    assert by_name["销售额"]["severity"] == "significant"
    assert by_name["退款率"]["delta_unit"] == "pp"
    assert by_name["退款率"]["delta_value"] == round(
        current["refund_rate"] - previous["refund_rate"], 2
    )
    assert by_name["退款率"]["severity"] is None
    assert check_same_period_false(report)["passed"] is True
    assert check_previous_comparison_present(report)["passed"] is True


def test_previous_comparison_delta_math_rejects_tampered_or_missing_entries():
    report, _history_context = period2_rerun_report()
    qa = load_period2_qa()
    tampered = deepcopy(report)
    tampered["previous_comparison"]["baseline"][0]["delta_value"] += 0.02
    missing = deepcopy(report)
    missing["previous_comparison"]["baseline"] = missing["previous_comparison"]["baseline"][1:]

    tampered_result = check_previous_comparison_delta_math(tampered, qa)
    missing_result = check_previous_comparison_delta_math(missing, qa)

    assert tampered_result["passed"] is False
    assert "销售额.delta_value" in tampered_result["details"]
    assert missing_result["passed"] is False
    assert "销售额: 对比卡缺少该指标" in missing_result["details"]


def test_previous_comparison_present_rejects_missing_or_malformed_section():
    assert check_previous_comparison_present({"findings": []})["passed"] is False
    malformed = {"previous_comparison": {"previous_report_id": "r-1", "baseline": "no"}}
    result = check_previous_comparison_present(malformed)
    assert result["passed"] is False
    assert "缺少字段" in result["details"]


def test_previous_report_resolvable_requires_founding_id_stored_in_isolated_db():
    report = {"previous_comparison": {"previous_report_id": "r-founding"}}
    rerun = {"founding_report_id": "r-founding", "stored_report_ids": ["r-founding", "r-rerun"]}

    assert check_previous_report_resolvable(report, rerun)["passed"] is True
    assert (
        check_previous_report_resolvable(report, {**rerun, "founding_report_id": "r-other"})[
            "passed"
        ]
        is False
    )
    assert (
        check_previous_report_resolvable(report, {**rerun, "stored_report_ids": ["r-rerun"]})[
            "passed"
        ]
        is False
    )


def test_same_period_false_assertion_flags_same_window_rerun():
    same_window = {"previous_comparison": {"same_period": True}}
    assert check_same_period_false(same_window)["passed"] is False
    assert check_same_period_false({"previous_comparison": {}})["passed"] is False


def test_previous_reference_signal_detects_keywords_and_baseline_values():
    report = {
        "summary": "本期销售额 327,985 元，较上期 390,037.19 元继续下滑。",
        "findings": [{"text": "徐汇店连续两期下滑"}],
        "previous_comparison": {
            "baseline": [{"name": "销售额", "previous_value": 390037.19}]
        },
    }

    signal = previous_reference_signal(report)
    silent = previous_reference_signal({"summary": "本期表现平稳。", "findings": []})

    assert "上期" in signal["keywords_matched"]
    assert "连续" in signal["keywords_matched"]
    assert signal["baseline_value_hits"] == ["销售额"]
    assert signal["any"] is True
    assert silent["any"] is False


def test_evaluate_report_adds_rerun_assertions_only_for_rerun_flow():
    report, _history_context = period2_rerun_report()
    table = load_table_from_path(
        PERIOD2_FIXTURE, original_filename=PERIOD2_FIXTURE.name, source_id="eval-test"
    )
    qa = load_period2_qa()

    plain = evaluate_report(report, table, qa)
    rerun = evaluate_report(
        report,
        table,
        qa,
        rerun={"founding_report_id": "r-founding", "stored_report_ids": ["r-founding"]},
    )

    assert [item["id"] for item in plain["hard_assertions"]][-1] == "count_invariants"
    assert [item["id"] for item in rerun["hard_assertions"]][-4:] == [
        "previous_comparison_present",
        "previous_report_resolvable",
        "previous_comparison_delta_math",
        "same_period_false",
    ]
    assert "previous_comparison" not in plain["key_values"]
    assert rerun["key_values"]["previous_comparison"]["previous_report_id"] == "r-founding"
    assert "previous_reference_signal" in rerun["observations"]


def test_load_golden_questions_accepts_rerun_flow_and_rejects_unknown_flow(tmp_path: Path):
    accepted = tmp_path / "ok.json"
    accepted.write_text(
        json.dumps(
            {
                "questions": [
                    {"id": "q1_run", "flow": "run"},
                    {"id": "q3_rerun", "flow": "rerun", "founding": {"data": "sample"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    rejected = tmp_path / "bad.json"
    rejected.write_text(
        json.dumps({"questions": [{"id": "q9", "flow": "replay"}]}), encoding="utf-8"
    )

    loaded = [question["id"] for question in load_golden_questions(accepted)]
    assert loaded == ["q1_run", "q3_rerun"]
    with pytest.raises(EvalSetupError):
        load_golden_questions(rejected)


def test_shipped_golden_questions_include_rerun_case_with_period2_fixture():
    questions = {question["id"]: question for question in load_golden_questions()}

    rerun_case = questions["q3_rerun_previous_comparison"]
    assert rerun_case["flow"] == "rerun"
    assert rerun_case["data"] == "fixtures/retail_sales_orders_period2.csv"
    assert rerun_case["founding"] == {"data": "sample"}
    assert rerun_case["goal"] == questions["q1_weekly_review"]["goal"]
    assert rerun_case["hard_assertions"][-4:] == [
        "previous_comparison_present",
        "previous_report_resolvable",
        "previous_comparison_delta_math",
        "same_period_false",
    ]


def test_single_run_result_surfaces_rerun_ids_for_acceptance_records():
    rerun_ids = {"task_id": "t-1", "founding_report_id": "r-1", "rerun_report_id": "r-2"}

    def execute_once():
        return {**execution_output(passed=True), "rerun": rerun_ids}

    result = run_repeated_question(
        {"id": "q3_rerun_previous_comparison"},
        repeat=1,
        execute_once=execute_once,
    )

    assert result["rerun"] == rerun_ids


# ---- 确定性层 · pack 校验规则 + capture 口径生效（architecture.md §7） ----
def display_name_headers_schema():
    from app.modules.context_pack_validation import display_name_schema

    return display_name_schema(load_default_context_pack())


def recognized_canonical_fields(pack: dict) -> set[str]:
    from app.modules.field_mapping import build_field_profile

    profile = build_field_profile(display_name_headers_schema(), pack)
    return {mapping.canonical_field for mapping in profile.mappings.values()}


def without_channel_aliases() -> dict:
    from copy import deepcopy as _deepcopy

    pack = _deepcopy(load_default_context_pack())
    for column in pack["data_dictionary"]["tables"][0]["columns"]:
        if column["name"] == "channel":
            column["aliases"] = ["投放渠道"]
    return pack


def test_pack_validation_rejects_alias_conflict_and_inverted_thresholds():
    from copy import deepcopy as _deepcopy

    from app.modules.context_pack_validation import validate_context_pack_edit

    broken = _deepcopy(load_default_context_pack())
    for column in broken["data_dictionary"]["tables"][0]["columns"]:
        if column["name"] == "category_l1":
            column["aliases"].append("销售渠道")
    broken["report_preferences"]["anomaly_thresholds"]["significant_pct"] = 40.0

    validation = validate_context_pack_edit(broken)

    assert validate_context_pack_edit(load_default_context_pack()).errors == []
    assert {issue.layer for issue in validation.errors} == {2}
    assert any("销售渠道" in issue.message for issue in validation.errors)
    assert any("标黄阈值必须小于标红阈值" in issue.message for issue in validation.errors)


def test_capture_alias_edit_changes_recognition_and_version_then_resets():
    """capture 确定性因果链（§7）：改口径 → 字段识别与版本追溯同时变化，reset 可还原。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        factory = client.get("/api/v1/context-pack").json()
        edited = client.put("/api/v1/context-pack", json=without_channel_aliases()).json()
        after_edit_sample = client.get("/api/v1/sample-dataset").json()
        restored = client.post("/api/v1/context-pack/reset").json()
        after_reset_sample = client.get("/api/v1/sample-dataset").json()

    assert factory["version"] == FACTORY_VERSION
    assert "channel" in recognized_canonical_fields(factory["payload"])

    assert edited["version"] == f"{FACTORY_VERSION}-local.1"
    assert after_edit_sample["context_pack_version"] == f"{FACTORY_VERSION}-local.1"
    assert "channel" not in recognized_canonical_fields(edited["payload"])

    assert restored["version"] == f"{FACTORY_VERSION}-local.2"
    assert after_reset_sample["context_pack_version"] == f"{FACTORY_VERSION}-local.2"
    assert "channel" in recognized_canonical_fields(restored["payload"])


# ---- 确定性层 · capture 用例（architecture.md §7 v0.13） ----
ZH_FIXTURE = BACKEND_DIR / "eval" / "fixtures" / "retail_sales_orders_zh.csv"
REQUIRED_FIELDS = ["net_sales_amount", "order_date"]


def zh_table():
    return load_table_from_path(
        ZH_FIXTURE,
        original_filename=ZH_FIXTURE.name,
        source_id="eval-capture-test",
    )


def recognized_for(pack: dict) -> list[str]:
    from app.modules.field_mapping import build_field_profile

    profile = build_field_profile(zh_table().schema_summary, pack)
    return sorted({mapping.canonical_field for mapping in profile.mappings.values()})


def capture_context(**overrides) -> dict:
    factory = recognized_for(load_default_context_pack())
    edited = recognized_for(without_channel_aliases())
    context = {
        "edited_fields": ["channel"],
        "required_fields": REQUIRED_FIELDS,
        "pre_edit": {"recognized": factory, "version": "1.0.0", "is_modified": False},
        "edited_version": "1.0.0-local.1",
        "report": {
            "report_id": "report-capture",
            "recognized": edited,
            "stored_version": "1.0.0-local.1",
        },
        "post_reset": {"recognized": factory, "version": "1.0.0-local.2", "is_modified": False},
    }
    context.update(overrides)
    return context


class ScriptedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = [json.dumps(response, ensure_ascii=False) for response in responses]

    def complete(self, _messages):
        if not self.responses:
            raise AssertionError("ScriptedLLM has no queued response")
        return self.responses.pop(0)


CAPTURE_SCRIPT = [
    {
        "tool": "query_data",
        "args": {
            "sql": (
                "SELECT store_name, SUM(net_sales_amount) AS sales FROM sales_orders "
                "WHERE order_date >= '2026-05-11' GROUP BY store_name ORDER BY sales LIMIT 5"
            )
        },
    },
    {
        "tool": "record_finding",
        "args": {
            "type": "anomaly",
            "text": "上海徐汇旗舰店本周销售额下滑最明显，需要复核。",
            "evidence": "query-1",
            "confidence": "medium",
        },
    },
    {"tool": "finish", "args": {"summary": "本周销售额回落，徐汇门店下滑最明显。"}},
]


def shipped_capture_question() -> dict:
    return next(question for question in load_golden_questions() if question["flow"] == "capture")


def test_capture_checks_are_red_unedited_green_edited_red_after_reset():
    """红→绿→红演示（§7 v0.13）：同一组 capture 判定在未编辑态与恢复后判红，编辑后判绿。"""
    from eval.assertions import capture_field_unrecognized_ok, capture_version_traced_ok

    factory = recognized_for(load_default_context_pack())
    edited = recognized_for(without_channel_aliases())

    assert "channel" in factory
    assert capture_field_unrecognized_ok(factory, ["channel"], REQUIRED_FIELDS) is False
    assert capture_version_traced_ok("1.0.0", "1.0.0", "1.0.0-local.1", "1.0.0") is False

    assert capture_field_unrecognized_ok(edited, ["channel"], REQUIRED_FIELDS) is True
    assert (
        capture_version_traced_ok("1.0.0-local.1", "1.0.0-local.1", "1.0.0-local.1", "1.0.0")
        is True
    )

    assert capture_field_unrecognized_ok(factory, ["channel"], REQUIRED_FIELDS) is False
    assert (
        capture_version_traced_ok("1.0.0-local.2", "1.0.0-local.2", "1.0.0-local.1", "1.0.0")
        is False
    )


def test_capture_checks_reject_vacuous_or_inconsistent_evidence():
    from eval.assertions import capture_field_unrecognized_ok, capture_version_traced_ok

    # 必需字段也没识别到 = 文件已不可分析，不能算「只少了 channel」的通过
    assert capture_field_unrecognized_ok(["store_name"], ["channel"], REQUIRED_FIELDS) is False
    # 编辑返回版本不是 -local.N / 报告与落库版本不一致 / 编辑前后版本相同
    assert capture_version_traced_ok("1.0.0", "1.0.0", "1.0.0", "0.9.0") is False
    assert (
        capture_version_traced_ok("1.0.0-local.1", "1.0.0", "1.0.0-local.1", "1.0.0") is False
    )
    assert (
        capture_version_traced_ok(
            "1.0.0-local.1", "1.0.0-local.1", "1.0.0-local.1", "1.0.0-local.1"
        )
        is False
    )


def test_capture_hard_assertions_and_control_detect_dirty_states():
    from eval.assertions import (
        check_capture_control,
        check_capture_field_unrecognized,
        check_capture_version_traced,
    )

    context = capture_context()
    edited_report = {"context_pack_version": "1.0.0-local.1"}
    assert check_capture_field_unrecognized(context)["passed"] is True
    assert check_capture_version_traced(edited_report, context)["passed"] is True
    assert check_capture_control(context)["passed"] is True

    factory = context["pre_edit"]["recognized"]
    edited = context["report"]["recognized"]
    unedited_report = capture_context(
        report={"report_id": "r", "recognized": factory, "stored_version": "1.0.0"}
    )
    assert check_capture_field_unrecognized(unedited_report)["passed"] is False
    assert check_capture_version_traced({"context_pack_version": "1.0.0"}, context)[
        "passed"
    ] is False
    assert check_capture_field_unrecognized(capture_context(report=None))["passed"] is False

    dirty_start = capture_context(
        pre_edit={"recognized": edited, "version": "1.0.0-local.1", "is_modified": True}
    )
    assert check_capture_control(dirty_start)["passed"] is False
    not_restored = capture_context(
        post_reset={"recognized": edited, "version": "1.0.0-local.2", "is_modified": True}
    )
    assert check_capture_control(not_restored)["passed"] is False


def test_finding_sql_replay_uses_the_given_pack_snapshot():
    report = {
        "findings": [
            {
                "text": "渠道结构",
                "evidence": {
                    "sql": "SELECT channel, COUNT(*) AS n FROM sales_orders GROUP BY channel",
                    "evidence_ref": "query-1",
                },
            }
        ]
    }

    factory = check_finding_sql(report, zh_table(), context_pack=load_default_context_pack())
    edited = check_finding_sql(report, zh_table(), context_pack=without_channel_aliases())

    assert factory["passed"] is True
    assert edited["passed"] is False


def test_evaluate_report_capture_flow_moves_anomaly_coverage_to_observations():
    edited_pack = without_channel_aliases()
    edited_pack["meta"]["version"] = "1.0.0-local.1"
    table = zh_table()
    report = generate_traceable_report(table, "帮我生成周度经营复盘", context_pack=edited_pack)
    qa = json.loads(ZH_FIXTURE.with_suffix(".qa.json").read_text(encoding="utf-8"))

    evaluation = evaluate_report(
        report,
        table,
        qa,
        capture=capture_context(),
        context_pack=edited_pack,
    )

    assert [item["id"] for item in evaluation["hard_assertions"]] == [
        "status_completed",
        "kpi_values_match",
        "finding_sql_replay",
        "count_invariants",
        "capture_field_unrecognized",
        "capture_version_traced",
        "capture_control",
    ]
    assert evaluation["observations"]["anomaly_coverage"]["matched_count"] >= 0
    assert "channel_values_mentioned" in evaluation["observations"]["capture_narrative_signal"]
    assert evaluation["key_values"]["capture"]["edited_version"] == "1.0.0-local.1"


def test_golden_question_declared_hard_assertions_match_evaluator_output():
    sample = load_retail_sample()
    sample_report = generate_traceable_report(sample, "帮我生成周度经营复盘")
    edited_pack = without_channel_aliases()
    capture_report = generate_traceable_report(
        zh_table(), "帮我生成周度经营复盘", context_pack=edited_pack
    )
    contexts = {
        "run": {},
        "rerun": {"rerun": {"founding_report_id": "f", "stored_report_ids": ["f"]}},
        "capture": {"capture": capture_context(), "context_pack": edited_pack},
    }

    for question in load_golden_questions():
        flow = question["flow"]
        if flow == "capture":
            report, table = capture_report, zh_table()
        else:
            report, table = sample_report, sample
        evaluation = evaluate_report(report, table, load_period1_qa(), **contexts[flow])
        produced = [item["id"] for item in evaluation["hard_assertions"]]
        assert produced == question["hard_assertions"], question["id"]


def test_load_golden_questions_requires_a_valid_pack_edit_for_capture(tmp_path: Path):
    base = {
        "id": "q9_capture_probe",
        "goal": "g",
        "data": "fixtures/retail_sales_orders_zh.csv",
        "flow": "capture",
    }
    path = tmp_path / "golden.json"
    invalid_edits = [
        {},
        {"pack_edit": {}},
        {"pack_edit": {"column_aliases": {}}},
        {"pack_edit": {"column_aliases": {"channel": "投放渠道"}}},
        {"pack_edit": {"column_aliases": {"channel": [" "]}}},
        {"pack_edit": {"anomaly_thresholds": {"significant_pct": 5}}},
    ]
    for invalid in invalid_edits:
        path.write_text(json.dumps({"questions": [{**base, **invalid}]}), encoding="utf-8")
        with pytest.raises(EvalSetupError):
            load_golden_questions(path)

    valid = {**base, "pack_edit": {"column_aliases": {"channel": ["投放渠道"]}}}
    path.write_text(json.dumps({"questions": [valid]}), encoding="utf-8")
    assert load_golden_questions(path)[0]["flow"] == "capture"


def test_shipped_golden_questions_include_alias_capture_case_on_zh_fixture():
    question = shipped_capture_question()

    assert question["data"] == "fixtures/retail_sales_orders_zh.csv"
    assert ZH_FIXTURE.exists() and ZH_FIXTURE.with_suffix(".qa.json").exists()
    assert question["pack_edit"] == {"column_aliases": {"channel": ["投放渠道"]}}
    assert "anomaly_coverage" not in question["hard_assertions"]
    assert {"capture_field_unrecognized", "capture_version_traced", "capture_control"} <= set(
        question["hard_assertions"]
    )


def test_capture_flow_edits_runs_restores_and_passes_every_gate(monkeypatch):
    from app.api.context_pack import is_modified
    from app.modules.context_pack import load_active_context_pack
    from eval.runner import execute_capture_question_once

    monkeypatch.setattr(
        "app.modules.report_runner.get_llm_client",
        lambda _settings=None: ScriptedLLM(CAPTURE_SCRIPT),
    )
    with temporary_eval_environment():
        output = execute_capture_question_once(
            shipped_capture_question(),
            settings=SimpleNamespace(llm_model="scripted-model"),
        )
        restored = load_active_context_pack()

    gates = {item["id"]: item for item in output["evaluation"]["hard_assertions"]}
    assert all(item["passed"] for item in gates.values()), {
        key: item["details"] for key, item in gates.items() if not item["passed"]
    }
    assert output["evaluation"]["passed"] is True
    assert output["report"]["context_pack_version"] == f"{FACTORY_VERSION}-local.1"
    assert output["capture"]["edited_version"] == f"{FACTORY_VERSION}-local.1"
    assert output["capture"]["post_reset"]["version"] == f"{FACTORY_VERSION}-local.2"
    assert "channel" not in output["capture"]["report"]["recognized"]
    assert "channel" in output["capture"]["pre_edit"]["recognized"]
    assert restored["meta"]["version"] == f"{FACTORY_VERSION}-local.2"
    assert is_modified(restored) is False


def test_capture_flow_restores_the_factory_pack_when_the_run_raises(monkeypatch):
    from app.api.context_pack import is_modified
    from app.modules.context_pack import load_active_context_pack
    from eval.runner import execute_capture_question_once

    def exploding_run(*_args, **_kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("eval.runner.execute_report_run", exploding_run)
    with temporary_eval_environment():
        with pytest.raises(RuntimeError):
            execute_capture_question_once(
                shipped_capture_question(),
                settings=SimpleNamespace(llm_model="scripted-model"),
            )
        restored = load_active_context_pack()

    assert restored["meta"]["version"] == f"{FACTORY_VERSION}-local.2"
    assert is_modified(restored) is False


def test_run_suite_records_factory_identity_before_questions_edit_the_pack(monkeypatch):
    from eval.runner import apply_pack_edit

    def editing_question(*_args, **_kwargs):
        apply_pack_edit({"channel": ["投放渠道"]})
        return {"id": "q4_capture_alias_edit", "passed": True, "observations": {}}

    monkeypatch.setattr("eval.runner.run_repeated_question", editing_question)
    suite = run_suite(
        [{"id": "q4_capture_alias_edit"}],
        settings=SimpleNamespace(normalized_provider="test", llm_model="test-model"),
        llm_client=object(),
        repeat=1,
        only=None,
    )

    assert suite["context_pack"]["version"] == FACTORY_VERSION


def test_capture_control_turns_red_only_for_the_right_reasons():
    """对照的鉴别力来自正确原因：两端都按出厂口径识别到被编辑字段与必需字段，版本单调前进。"""
    from eval.assertions import check_capture_control

    factory = recognized_for(load_default_context_pack())
    edited = recognized_for(without_channel_aliases())

    assert check_capture_control(capture_context())["passed"] is True
    # 编辑前什么都没识别：字段断言也会判红，但原因不对
    assert check_capture_control(
        capture_context(pre_edit={"recognized": [], "version": "1.0.0", "is_modified": False})
    )["passed"] is False
    # 编辑前本就不识别渠道（起点不是出厂识别）
    assert check_capture_control(
        capture_context(pre_edit={"recognized": edited, "version": "1.0.0", "is_modified": False})
    )["passed"] is False
    # 恢复后版本回到编辑前或停在编辑版本：revision 没有单调前进
    for regressed in ("1.0.0", "1.0.0-local.1"):
        assert check_capture_control(
            capture_context(
                post_reset={"recognized": factory, "version": regressed, "is_modified": False}
            )
        )["passed"] is False, regressed


def count_pack_reads(monkeypatch) -> list[int]:
    from app.modules import context_pack as context_pack_module

    calls: list[int] = []
    original = context_pack_module.read_active_context_pack_record

    def counting_read():
        calls.append(1)
        return original()

    monkeypatch.setattr(context_pack_module, "read_active_context_pack_record", counting_read)
    return calls


def test_capture_flow_hands_one_edited_snapshot_to_the_run_and_the_replay(monkeypatch):
    import eval.runner as runner_module

    seen: dict[str, dict | None] = {}
    original_run = runner_module.execute_report_run
    original_evaluate = runner_module.evaluate_report

    def spying_run(table, task, **kwargs):
        seen["run"] = kwargs.get("context_pack")
        return original_run(table, task, **kwargs)

    def spying_evaluate(report, table, qa, **kwargs):
        seen["evaluate"] = kwargs.get("context_pack")
        return original_evaluate(report, table, qa, **kwargs)

    monkeypatch.setattr(runner_module, "execute_report_run", spying_run)
    monkeypatch.setattr(runner_module, "evaluate_report", spying_evaluate)
    monkeypatch.setattr(
        "app.modules.report_runner.get_llm_client",
        lambda _settings=None: ScriptedLLM(CAPTURE_SCRIPT),
    )
    with temporary_eval_environment():
        runner_module.execute_capture_question_once(
            shipped_capture_question(),
            settings=SimpleNamespace(llm_model="scripted-model"),
        )

    assert seen["run"] is not None and seen["run"] is seen["evaluate"]
    assert seen["run"]["meta"]["version"] == f"{FACTORY_VERSION}-local.1"


def test_run_and_rerun_flows_resolve_the_active_pack_once(monkeypatch):
    from eval.runner import execute_question_once

    questions = {question["flow"]: question for question in load_golden_questions()}
    monkeypatch.setattr(
        "app.modules.report_runner.get_llm_client",
        lambda _settings=None: ScriptedLLM(CAPTURE_SCRIPT),
    )
    reads: dict[str, int] = {}
    with temporary_eval_environment():
        for flow in ("run", "rerun"):
            calls = count_pack_reads(monkeypatch)
            execute_question_once(
                questions[flow],
                settings=SimpleNamespace(llm_model="scripted-model"),
                llm_client=ScriptedLLM(CAPTURE_SCRIPT),
            )
            reads[flow] = len(calls)

    assert reads == {"run": 1, "rerun": 1}
