from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db.engine import SessionLocal, get_engine, init_db
from app.llm.client import get_llm_client
from app.modules.analysis_loop import run_analysis_loop
from app.modules.context_pack import load_active_context_pack
from app.modules.persistence import save_report_run
from app.modules.reporting import generate_traceable_report
from app.modules.schemas import TableData


def execute_report_run(
    table: TableData,
    task: dict[str, Any],
    *,
    task_id: str | None = None,
    history_context: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """共享报告内核：/reports/run 与任务重跑共用；history_context 仅重跑且有上期时传入。

    活动包在一次运行内只解析一次并向下传递：字段识别、口径注入与报告口径版本必须同源。
    """
    pack = context_pack if context_pack is not None else load_active_context_pack()
    settings = get_settings()
    llm_client = get_llm_client(settings)
    if llm_client is None:
        report = generate_traceable_report(
            table,
            str(task["analysis_goal"]),
            history_context=history_context,
            context_pack=pack,
        )
    else:
        report = run_analysis_loop(
            table,
            task,
            llm_client,
            model_name=settings.llm_model,
            history_context=history_context,
            context_pack=pack,
        )
    if report["status"] == "failed":
        return None, report

    init_db()
    with SessionLocal(bind=get_engine()) as session:
        report_id = save_report_run(
            session,
            table,
            task,
            report,
            task_id=task_id,
            context_pack=pack,
        )
        session.commit()
    return report_id, report
