from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import Report
from app.llm.client import LLMClientProtocol, get_llm_client
from app.modules.analysis_loop import run_analysis_loop
from app.modules.context_pack import (
    context_pack_identity,
    effective_version,
    load_active_context_pack,
)
from app.modules.context_pack_validation import validate_context_pack_edit
from app.modules.field_mapping import REQUIRED_FIELDS, build_field_profile
from app.modules.file_ingestion import load_table_from_path
from app.modules.history_context import history_context_for_task
from app.modules.persistence import (
    ensure_seeded_context_pack,
    reset_context_pack,
    save_context_pack,
    save_report_run,
    save_task,
)
from app.modules.report_runner import execute_report_run
from app.modules.reporting import default_structured_task, generate_traceable_report
from app.modules.sample_data import load_retail_sample
from app.modules.schemas import TableData
from app.modules.task_fingerprint import canonical_fields_from_profile
from app.modules.task_parser import context_pack_for_llm, sanitize_error
from eval.assertions import evaluate_report

BACKEND_DIR = Path(__file__).resolve().parents[1]
GOLDEN_QUESTIONS_PATH = Path(__file__).resolve().parent / "golden_questions.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline" / "baseline.json"
PERIOD1_QA_PATH = BACKEND_DIR / ".sample-data-qa.json"
SUPPORTED_FLOWS = {"run", "rerun", "capture"}
SUPPORTED_PACK_EDITS = {"column_aliases"}


@dataclass(frozen=True)
class EvalEnvironment:
    data_dir: Path
    upload_dir: Path
    database_path: Path
    database_url: str


class EvalSetupError(ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.repeat < 1:
        print("--repeat 必须大于等于 1。", file=sys.stderr)
        return 2
    if args.update_baseline and args.repeat != 1:
        print("--update-baseline 只允许在 --repeat 1 下执行。", file=sys.stderr)
        return 2
    if args.update_baseline and args.only is not None:
        print("--update-baseline 不允许与 --only 组合，以免覆盖为不完整基线。", file=sys.stderr)
        return 2

    try:
        settings = get_settings()
        llm_client = get_llm_client(settings)
        if llm_client is None:
            print(
                "未配置真实 LLM，无法运行报告质量 eval。请先在 UI 或 .env 配置并启用模型。",
                file=sys.stderr,
            )
            return 2
        questions = load_golden_questions()
        suite = run_suite(
            questions,
            settings=settings,
            llm_client=llm_client,
            repeat=args.repeat,
            only=args.only,
        )
        if args.update_baseline:
            if not suite["passed"]:
                print(json.dumps(suite, ensure_ascii=False, indent=2))
                print("eval: FAIL；硬断言未全绿，未更新基线。", file=sys.stderr)
                return 1
            write_baseline(suite)
            suite["baseline"] = {
                "updated": True,
                "path": str(BASELINE_PATH.relative_to(BACKEND_DIR)),
            }
        else:
            suite["baseline"] = compare_with_baseline(suite)
    except (EvalSetupError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"eval 设置失败：{sanitize_eval_error(exc)}", file=sys.stderr)
        return 2

    print(json.dumps(suite, ensure_ascii=False, indent=2))
    if suite["passed"]:
        print("eval: PASS")
        return 0
    print("eval: FAIL", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data Insight Agent report-quality eval")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only")
    return parser


def load_golden_questions(path: Path = GOLDEN_QUESTIONS_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise EvalSetupError("golden_questions.json 未包含有效 questions。")
    for question in questions:
        if not isinstance(question, dict) or not isinstance(question.get("id"), str):
            raise EvalSetupError("golden question 缺少有效 id。")
        if question.get("flow") not in SUPPORTED_FLOWS:
            raise EvalSetupError("golden question 的 flow 只支持 run / rerun / capture。")
        if question["flow"] == "capture":
            validate_pack_edit_spec(question)
    return questions


def validate_pack_edit_spec(question: dict[str, Any]) -> None:
    """capture 用例的 pack_edit（§7 v0.13）：当前仅支持 column_aliases 整列替换别名。"""
    spec = question.get("pack_edit")
    label = f"capture 用例 {question.get('id')} 的 pack_edit"
    if not isinstance(spec, dict) or not spec or set(spec) - SUPPORTED_PACK_EDITS:
        raise EvalSetupError(f"{label} 只支持 column_aliases。")
    column_aliases = spec.get("column_aliases")
    if not isinstance(column_aliases, dict) or not column_aliases:
        raise EvalSetupError(f"{label} 的 column_aliases 必须是非空对象。")
    for column, aliases in column_aliases.items():
        if (
            not isinstance(column, str)
            or not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
        ):
            raise EvalSetupError(f"{label} 中 {column} 的别名必须是非空字符串列表。")


def resolve_questions(
    questions: list[dict[str, Any]],
    selector: str | None,
) -> list[dict[str, Any]]:
    if selector is None:
        return questions
    selected = [
        question
        for question in questions
        if question["id"] == selector or question["id"].startswith(f"{selector}_")
    ]
    if not selected:
        available = ", ".join(question["id"] for question in questions)
        raise EvalSetupError(f"未找到用例 {selector!r}；可选：{available}")
    return selected


def run_suite(
    questions: list[dict[str, Any]],
    *,
    settings: Settings,
    llm_client: LLMClientProtocol,
    repeat: int,
    only: str | None,
) -> dict[str, Any]:
    selected = resolve_questions(questions, only)
    with temporary_eval_environment():
        # 套件口径身份在任何用例之前读取：capture 用例的编辑与恢复会推进 revision（§7 v0.13）。
        identity = context_pack_identity()
        question_results = [
            run_repeated_question(
                question,
                repeat=repeat,
                execute_once=lambda question=question: execute_question_once(
                    question,
                    settings=settings,
                    llm_client=llm_client,
                ),
            )
            for question in selected
        ]

    return {
        "schema_version": 1,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": {
            "provider": settings.normalized_provider,
            "name": settings.llm_model,
        },
        "context_pack": {
            "name": identity["context_pack_name"],
            "version": identity["context_pack_version"],
        },
        "repeat": repeat,
        "selected": [question["id"] for question in selected],
        "passed": all(result["passed"] for result in question_results),
        "questions": question_results,
    }


def run_repeated_question(
    question: dict[str, Any],
    *,
    repeat: int,
    execute_once: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    runs = [run_question_with_retry(question, execute_once) for _ in range(repeat)]
    result: dict[str, Any] = {
        "id": question["id"],
        "goal": question.get("goal"),
        "data": question.get("data"),
        "flow": question.get("flow"),
        "passed": all(run["passed"] for run in runs),
        "runs": runs,
        "observations": aggregate_observations([run["observations"] for run in runs]),
    }
    if repeat == 1:
        result["hard_assertions"] = runs[0]["hard_assertions"]
        result["key_values"] = runs[0]["key_values"]
        result["attempts"] = runs[0]["attempts"]
        for evidence_key in ("rerun", "capture"):
            if evidence_key in runs[0]:
                result[evidence_key] = runs[0][evidence_key]
    return result


def run_question_with_retry(
    question: dict[str, Any],
    execute_once: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    attempt_summaries: list[dict[str, Any]] = []
    last_output: dict[str, Any] | None = None
    for attempt in range(1, 3):
        output = execute_once()
        last_output = output
        report = output["report"]
        evaluation = output["evaluation"]
        warning_codes = [
            str(warning.get("code"))
            for warning in report.get("warnings", [])
            if isinstance(warning, dict) and warning.get("code")
        ]
        attempt_summaries.append(
            {
                "attempt": attempt,
                "status": report.get("status"),
                "passed": evaluation["passed"],
                "warning_codes": warning_codes,
                "duration_seconds": output["duration_seconds"],
            }
        )
        if "LLM_CALL_FAILED" not in warning_codes:
            break

    if last_output is None:
        raise EvalSetupError(f"用例 {question.get('id')} 未执行。")
    evaluation = last_output["evaluation"]
    observations = {
        **evaluation["observations"],
        "duration_seconds": last_output["duration_seconds"],
        "pack_prompt_estimated_tokens": last_output.get("pack_prompt_estimated_tokens"),
    }
    result = {
        "passed": evaluation["passed"],
        "attempts": len(attempt_summaries),
        "attempt_summaries": attempt_summaries,
        "hard_assertions": evaluation["hard_assertions"],
        "key_values": evaluation["key_values"],
        "observations": observations,
    }
    for evidence_key in ("rerun", "capture"):
        if evidence_key in last_output:
            result[evidence_key] = last_output[evidence_key]
    return result


def execute_question_once(
    question: dict[str, Any],
    *,
    settings: Settings,
    llm_client: LLMClientProtocol,
) -> dict[str, Any]:
    if question.get("flow") == "rerun":
        return execute_rerun_question_once(question, settings=settings)
    if question.get("flow") == "capture":
        return execute_capture_question_once(question, settings=settings)
    table, qa = load_question_data(question)
    # 一次用例只解析一次活动包，任务、分析、SQL 重放与体积估算同源（§6.4 单次运行同源）。
    pack = load_active_context_pack()
    goal = str(question.get("goal") or "")
    task = default_structured_task(goal, asdict(table.data_source_ref), context_pack=pack)
    started = time.monotonic()
    report = run_analysis_loop(
        table,
        task,
        llm_client,
        model_name=settings.llm_model,
        context_pack=pack,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    evaluation = evaluate_report(report, table, qa, context_pack=pack)
    return {
        "report": report,
        "evaluation": evaluation,
        "duration_seconds": duration_seconds,
        "pack_prompt_estimated_tokens": estimate_pack_prompt_tokens(pack),
    }


def execute_rerun_question_once(
    question: dict[str, Any],
    *,
    settings: Settings,
) -> dict[str, Any]:
    """rerun 用例（§7 v0.10）：确定性 founding 落隔离库 → 建任务 → 真实 LLM 重跑。"""
    founding = question.get("founding")
    founding = founding if isinstance(founding, dict) else {}
    founding_question = {**question, "data": founding.get("data", "sample")}
    founding_table, _founding_qa = load_question_data(founding_question)
    pack = load_active_context_pack()
    goal = str(question.get("goal") or "")
    founding_task = default_structured_task(
        goal,
        asdict(founding_table.data_source_ref),
        context_pack=pack,
    )
    founding_report = generate_traceable_report(founding_table, goal, context_pack=pack)
    if founding_report.get("status") != "completed":
        raise EvalSetupError(f"用例 {question.get('id')} 的 founding 报告未完成。")

    init_db()
    with SessionLocal(bind=get_engine()) as session:
        founding_report_id = save_report_run(
            session, founding_table, founding_task, founding_report, context_pack=pack
        )
        stored = session.get(Report, founding_report_id)
        if stored is None:
            raise EvalSetupError("founding 报告未写入隔离库。")
        task = save_task(session, stored, title=f"eval:{question.get('id')}")
        session.commit()
        history_context = history_context_for_task(task)
        task_id = task.id
        rerun_task = deepcopy(task.structured_task_json)
    if history_context is None:
        raise EvalSetupError("founding 报告入链后未能构建 history_context。")

    table, qa = load_question_data(question)
    rerun_task["data_source_ref"] = asdict(table.data_source_ref)
    started = time.monotonic()
    rerun_report_id, report = execute_report_run(
        table,
        rerun_task,
        task_id=task_id,
        history_context=history_context,
        context_pack=pack,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    with SessionLocal(bind=get_engine()) as session:
        stored_report_ids = [str(item) for item in session.scalars(select(Report.id)).all()]
    rerun_context = {
        "founding_report_id": founding_report_id,
        "stored_report_ids": stored_report_ids,
    }
    evaluation = evaluate_report(report, table, qa, rerun=rerun_context, context_pack=pack)
    return {
        "report": report,
        "evaluation": evaluation,
        "duration_seconds": duration_seconds,
        "pack_prompt_estimated_tokens": estimate_pack_prompt_tokens(pack),
        "rerun": {
            "task_id": task_id,
            "founding_report_id": founding_report_id,
            "rerun_report_id": rerun_report_id,
            "model": settings.llm_model,
        },
    }


def execute_capture_question_once(
    question: dict[str, Any],
    *,
    settings: Settings,
) -> dict[str, Any]:
    """capture 用例（§7 v0.13）：隔离库内编辑口径 → 真实 LLM 生成落库 → finally 恢复 → 断言。"""
    table, qa = load_question_data(question)
    column_aliases = question["pack_edit"]["column_aliases"]
    pre_edit = pack_snapshot(table)
    edited_version = apply_pack_edit(column_aliases)
    try:
        edited_pack = load_active_context_pack()
        goal = str(question.get("goal") or "")
        task = default_structured_task(
            goal,
            asdict(table.data_source_ref),
            context_pack=edited_pack,
        )
        started = time.monotonic()
        report_id, report = execute_report_run(table, task, context_pack=edited_pack)
        duration_seconds = round(time.monotonic() - started, 3)
        stored = stored_capture_record(report_id)
    finally:
        restore_factory_pack()
    post_reset = pack_snapshot(table)

    capture = {
        "edited_fields": sorted(column_aliases),
        "required_fields": list(REQUIRED_FIELDS),
        "pre_edit": pre_edit,
        "edited_version": edited_version,
        "report": stored,
        "post_reset": post_reset,
    }
    evaluation = evaluate_report(report, table, qa, capture=capture, context_pack=edited_pack)
    return {
        "report": report,
        "evaluation": evaluation,
        "duration_seconds": duration_seconds,
        "pack_prompt_estimated_tokens": estimate_pack_prompt_tokens(edited_pack),
        "capture": {**capture, "model": settings.llm_model},
    }


def apply_pack_edit(column_aliases: dict[str, list[str]]) -> str:
    """与 PUT /context-pack 相同的四层校验与保存函数写入编辑；返回保存后的有效版本串。"""
    candidate = load_active_context_pack()
    columns = candidate["data_dictionary"]["tables"][0]["columns"]
    unknown = sorted(set(column_aliases) - {column["name"] for column in columns})
    if unknown:
        raise EvalSetupError(f"pack_edit 引用了不存在的字段：{', '.join(unknown)}")
    for column in columns:
        if column["name"] in column_aliases:
            column["aliases"] = list(column_aliases[column["name"]])

    validation = validate_context_pack_edit(candidate)
    if not validation.passed:
        messages = "；".join(issue.message for issue in validation.errors)
        raise EvalSetupError(f"capture 口径编辑未通过校验：{messages}")
    with SessionLocal(bind=get_engine()) as session:
        record = save_context_pack(session, validation.payload)
        session.commit()
        return effective_version(record.base_version, record.revision)


def restore_factory_pack() -> None:
    """与 POST /context-pack/reset 相同的恢复函数：还原出厂内容，revision 照常 +1。"""
    with SessionLocal(bind=get_engine()) as session:
        reset_context_pack(session)
        session.commit()


def pack_snapshot(table: TableData) -> dict[str, Any]:
    """一次读取活动口径：该数据的识别字段集 + 有效版本 + 是否偏离出厂（与 API 同一判定）。"""
    from app.api.context_pack import is_modified

    pack = load_active_context_pack()
    profile = build_field_profile(table.schema_summary, pack)
    return {
        "recognized": sorted({mapping.canonical_field for mapping in profile.mappings.values()}),
        "version": pack["meta"]["version"],
        "is_modified": is_modified(pack),
    }


def stored_capture_record(report_id: str | None) -> dict[str, Any] | None:
    """读回该次运行落库的数据集字段识别与报告口径版本——产品自己的记录才是因果链证据。"""
    if report_id is None:
        return None
    with SessionLocal(bind=get_engine()) as session:
        stored = session.get(Report, report_id)
        if stored is None:
            return None
        recognized = canonical_fields_from_profile(stored.dataset.field_profile_json or {})
        return {
            "report_id": report_id,
            "recognized": sorted(recognized),
            "stored_version": stored.context_pack_version,
        }


def load_question_data(question: dict[str, Any]) -> tuple[TableData, dict[str, Any]]:
    data = question.get("data")
    if data == "sample":
        return load_retail_sample(), load_json(PERIOD1_QA_PATH)
    if not isinstance(data, str) or not data.startswith("fixtures/"):
        raise EvalSetupError(f"用例 {question.get('id')} 的 data 不受支持。")
    relative_path = Path(data).relative_to("fixtures")
    fixture_path = (FIXTURES_DIR / relative_path).resolve()
    if FIXTURES_DIR.resolve() not in fixture_path.parents:
        raise EvalSetupError("fixture 路径越界。")
    qa_path = fixture_path.with_suffix(".qa.json")
    table = load_table_from_path(
        fixture_path,
        original_filename=fixture_path.name,
        source_id=f"eval-{question['id']}",
    )
    return table, load_json(qa_path)


@contextmanager
def temporary_eval_environment(base_dir: Path | None = None) -> Iterator[EvalEnvironment]:
    from app.api import runtime
    from app.db import engine as engine_module

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if base_dir is None:
        temporary_directory = tempfile.TemporaryDirectory(prefix="data-insight-eval-")
        root = Path(temporary_directory.name)
    else:
        root = Path(base_dir)
        root.mkdir(parents=True, exist_ok=True)

    data_dir = root / "data"
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "app.db"
    database_url = f"sqlite:///{database_path}"
    environment = EvalEnvironment(
        data_dir=data_dir,
        upload_dir=upload_dir,
        database_path=database_path,
        database_url=database_url,
    )

    had_database_url = "APP_DB_URL" in os.environ
    original_database_url = os.environ.get("APP_DB_URL")
    original_data_dir = runtime.DATA_DIR
    original_upload_dir = runtime.UPLOAD_DIR
    original_sessions = runtime.UPLOAD_SESSIONS
    os.environ["APP_DB_URL"] = database_url
    runtime.DATA_DIR = data_dir
    runtime.UPLOAD_DIR = upload_dir
    runtime.UPLOAD_SESSIONS = {}
    try:
        # 隔离库内建表并种子活动包：用例跑在与生产同形的活动包上（内容仍是出厂内容），
        # 且 capture 用例可以在隔离库内直接 PUT 改口径。
        init_db()
        ensure_seeded_context_pack()
        yield environment
    finally:
        normalized_database_url = engine_module.normalize_database_url(database_url)
        cached_engine = engine_module._engine_cache.pop(normalized_database_url, None)
        if cached_engine is not None:
            cached_engine.dispose()
        runtime.DATA_DIR = original_data_dir
        runtime.UPLOAD_DIR = original_upload_dir
        runtime.UPLOAD_SESSIONS = original_sessions
        if had_database_url and original_database_url is not None:
            os.environ["APP_DB_URL"] = original_database_url
        else:
            os.environ.pop("APP_DB_URL", None)
        if temporary_directory is not None:
            temporary_directory.cleanup()


def write_baseline(suite: dict[str, Any], path: Path = BASELINE_PATH) -> None:
    baseline = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).date().isoformat(),
        "model": suite["model"],
        "context_pack": suite["context_pack"],
        "questions": [
            {
                "id": question["id"],
                "passed": question["passed"],
                "hard_assertions": question["hard_assertions"],
                "key_values": question["key_values"],
                "observations": question["observations"],
            }
            for question in suite["questions"]
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_with_baseline(
    suite: dict[str, Any],
    path: Path = BASELINE_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return {"found": False, "message": "尚未建立基线，请运行 make eval-baseline。"}
    baseline = load_json(path)
    baseline_by_id = {
        question["id"]: question
        for question in baseline.get("questions", [])
        if isinstance(question, dict) and question.get("id")
    }
    observation_diffs = {}
    for question in suite["questions"]:
        previous = baseline_by_id.get(question["id"], {})
        observation_diffs[question["id"]] = {
            "baseline": previous.get("observations"),
            "current": question.get("observations"),
        }
    return {
        "found": True,
        "generated_at": baseline.get("generated_at"),
        "model": baseline.get("model"),
        "observation_diffs": observation_diffs,
    }


def aggregate_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    if len(observations) == 1:
        return observations[0]
    keys = sorted({key for item in observations for key in item})
    aggregated: dict[str, Any] = {}
    for key in keys:
        values = [item.get(key) for item in observations]
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            numeric_values = [float(value) for value in values]
            aggregated[key] = {
                "mean": round(mean(numeric_values), 3),
                "min": min(numeric_values),
                "max": max(numeric_values),
            }
        else:
            aggregated[key] = values
    return aggregated


def estimate_pack_prompt_tokens(pack: dict[str, Any] | None = None) -> int:
    payload = context_pack_for_llm(pack if pack is not None else load_active_context_pack())
    text = json.dumps(payload, ensure_ascii=False)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return max(1, ascii_chars // 4 + len(text) - ascii_chars)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvalSetupError(f"{path.name} 必须是 JSON object。")
    return payload


def sanitize_eval_error(exc: Exception) -> str:
    text = sanitize_error(exc)
    known_roots = sorted(
        {
            str(BACKEND_DIR),
            str(BACKEND_DIR.parent),
            tempfile.gettempdir(),
        },
        key=len,
        reverse=True,
    )
    for root in known_roots:
        text = text.replace(root, "[redacted-path]")
    return text


if __name__ == "__main__":
    raise SystemExit(main())
