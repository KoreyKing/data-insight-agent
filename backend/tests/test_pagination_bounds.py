"""列表分页边界（architecture.md §2）：limit / offset 一律夹逼后原样回显，不把越界入参抛成 500。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.history_serializers import MAX_LIMIT, MAX_OFFSET, normalize_pagination
from app.main import app
from tests.test_tasks_api import create_report_fixture

LIST_PATHS = ("/api/v1/tasks", "/api/v1/reports", "/api/v1/datasets", "/api/v1/feedback")
# 2**63 是 SQLite 绑定参数第一个越界值，10**30 代表任意更大的入参。
OUT_OF_RANGE_OFFSETS = (2**63, 10**30)


def items_of(payload: dict) -> list:
    return payload["tasks"] if "tasks" in payload else payload["items"]


@pytest.mark.parametrize("offset", OUT_OF_RANGE_OFFSETS)
@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_endpoints_clamp_out_of_range_offset_instead_of_failing(
    tmp_path: Path,
    path: str,
    offset: int,
):
    report_id, _ = create_report_fixture(tmp_path, f"offset-{path.rsplit('/', 1)[-1]}")
    with TestClient(app) as client:
        assert client.post("/api/v1/tasks", json={"report_id": report_id}).status_code == 201
        assert (
            client.post(
                f"/api/v1/reports/{report_id}/feedback",
                json={"verdict": "useful"},
            ).status_code
            == 200
        )
        # 有数据在库时才能证明「翻过所有行返回空列表」，而不是库空导致的空。
        assert items_of(client.get(path).json())

        response = client.get(path, params={"offset": offset})

    assert response.status_code == 200
    payload = response.json()
    assert payload["offset"] == MAX_OFFSET
    assert items_of(payload) == []


def test_normalize_pagination_clamps_both_bounds():
    assert normalize_pagination(20, 0) == (20, 0)
    assert normalize_pagination(999, -5) == (MAX_LIMIT, 0)
    assert normalize_pagination(1, MAX_OFFSET) == (1, MAX_OFFSET)
    assert normalize_pagination(1, MAX_OFFSET + 1) == (1, MAX_OFFSET)
    assert normalize_pagination(1, 10**30) == (1, MAX_OFFSET)
