"""conftest 隔离夹具的自检：测试期间上传与应用库都不得落到仓库 data/ 目录。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

REPO_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def test_upload_dir_and_sessions_are_isolated_from_repo_data():
    from app.api import runtime, uploads

    assert runtime.UPLOAD_DIR == uploads.UPLOAD_DIR
    assert runtime.UPLOAD_SESSIONS is uploads.UPLOAD_SESSIONS
    assert REPO_DATA_DIR not in runtime.UPLOAD_DIR.parents
    assert REPO_DATA_DIR not in Path(os.environ["APP_DB_URL"].removeprefix("sqlite:///")).parents


def test_upload_api_writes_only_into_isolated_directory():
    from app.api import runtime

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("probe.csv", "订单日期,销售额\n2026-05-11,1\n".encode(), "text/csv")},
        )

    assert response.status_code == 200
    session_id = response.json()["session_id"]
    stored = Path(runtime.UPLOAD_SESSIONS[session_id]["path"])
    assert runtime.UPLOAD_DIR in stored.parents
    assert not (REPO_DATA_DIR / "uploads" / session_id).exists()
