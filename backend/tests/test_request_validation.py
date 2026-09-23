"""请求体边界校验（architecture.md §2 v0.15）。

无法以 UTF-8 编码的字符串一律 400，不留到 SQLite 绑定或响应序列化才炸成 500。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.request_validation import contains_unencodable
from app.db.engine import SessionLocal, get_engine
from app.db.models import AnalysisTask, ContextPackRecord, Report
from app.main import app
from tests.test_tasks_api import create_report_fixture

INVALID_BODY = {
    "code": "REQUEST_BODY_INVALID",
    "message": "请求内容包含无法处理的字符，请检查后重试。",
}


def body(raw: str) -> dict:
    """raw 是 JSON 源文本：`\\ud800` 在传输上是合法 ASCII，解码后才成为孤立代理项。"""
    return {"content": raw.encode("utf-8"), "headers": {"content-type": "application/json"}}


def test_contains_unencodable_scans_keys_values_and_nesting():
    assert contains_unencodable("\ud800") is True
    assert contains_unencodable({"k": ["ok", {"deep": "\ud800"}]}) is True
    assert contains_unencodable({"\ud800": "ok"}) is True  # 字典键同样要查
    assert contains_unencodable({"k": ["中文", "emoji ✅", "𝄞", 1, None, True]}) is False
    assert contains_unencodable([]) is False


def test_deeply_nested_body_does_not_blow_the_scanner():
    """扫描是迭代而非递归：深层嵌套不会把校验自己压爆栈。"""
    payload: object = "\ud800"
    for _ in range(5000):
        payload = {"n": payload}
    assert contains_unencodable(payload) is True


@pytest.mark.parametrize(
    ("method", "path", "raw"),
    [
        ("post", "/api/v1/tasks/parse", r'{"analysis_goal": "\ud800"}'),
        ("post", "/api/v1/reports/run", r'{"analysis_goal": "\ud800"}'),
        # task 是开放式字典合并，字段无法穷举——正是边界校验存在的理由。
        ("post", "/api/v1/reports/run", r'{"task": {"任意新字段": "\ud800"}}'),
        ("post", "/api/v1/reports/run", r'{"task": {"\ud800": "x"}}'),
        ("post", "/api/v1/reports/run", r'{"task": {"a": {"b": ["\ud800"]}}}'),
        ("post", "/api/v1/tasks", r'{"report_id": "\ud800"}'),
        ("put", "/api/v1/context-pack", r'{"meta": {"name": "\ud800"}}'),
        ("post", "/api/v1/llm-config", r'{"provider": "openai", "model": "\ud800"}'),
    ],
)
def test_unencodable_body_is_rejected_at_the_boundary(method: str, path: str, raw: str):
    with TestClient(app) as client:
        response = getattr(client, method)(path, **body(raw))

    assert response.status_code == 400
    assert response.json() == INVALID_BODY


def test_rejection_happens_before_any_write(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "boundary-nowrite")
    with TestClient(app) as client:
        titled = body(f'{{"report_id": "{report_id}", "title": "\\ud800"}}')
        assert client.post("/api/v1/tasks", **titled).status_code == 400
        run = body(r'{"analysis_goal": "\ud800"}')
        assert client.post("/api/v1/reports/run", **run).status_code == 400

    with SessionLocal(bind=get_engine()) as session:
        # 任务未创建、报告未新增（fixture 那份仍是唯一一份）、founding 报告未被归链。
        assert session.query(AnalysisTask).count() == 0
        assert session.query(Report).count() == 1
        assert session.get(Report, report_id).task_id is None


def test_legitimate_non_ascii_bodies_are_not_over_rejected(tmp_path: Path):
    """中文、emoji、成对代理项（𝄞）都是合法 UTF-8，不能被误伤。"""
    report_id, _ = create_report_fixture(tmp_path, "boundary-ok")
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"report_id": report_id})
        renamed = client.patch(
            f"/api/v1/tasks/{created.json()['id']}",
            json={"title": "中文任务名 ✅ 𝄞 café"},
        )

    assert created.status_code == 201
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "中文任务名 ✅ 𝄞 café"


def test_guard_does_not_consume_multipart_upload_body():
    """上传走 multipart：校验必须跳过，否则会吞掉文件流。"""
    csv = "订单日期,销售额,门店\n2026-08-20,100,成都店\n"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("sales.csv", csv.encode("utf-8"), "text/csv")},
        )

    assert response.status_code == 200
    assert response.json()["session_id"]


def test_malformed_json_still_falls_through_to_framework_422():
    """非法 JSON 不归边界校验管，仍由 FastAPI 回 422。"""
    with TestClient(app) as client:
        response = client.post("/api/v1/tasks", **body("{not json"))

    assert response.status_code == 422


def test_context_pack_is_untouched_when_body_is_rejected():
    with TestClient(app) as client:
        before = client.get("/api/v1/context-pack").json()
        rejected = client.put("/api/v1/context-pack", **body(r'{"meta": {"name": "\ud800"}}'))
        after = client.get("/api/v1/context-pack").json()

    assert rejected.status_code == 400
    assert before["revision"] == after["revision"]
    assert before["payload"] == after["payload"]
    with SessionLocal(bind=get_engine()) as session:
        assert session.query(ContextPackRecord).count() == 1
