import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fonts_get_a_font_type_without_system_mime_tables():
    # 精简镜像没有 /etc/mime.types：只用 Python 内置表导入应用，woff2 仍须按 font/woff2 返回
    code = (
        "import mimetypes; mimetypes.knownfiles = []; mimetypes.init(); import app.main; "
        "print(mimetypes.guess_type('font.woff2')[0])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=BACKEND_DIR
    )
    assert result.stdout.strip() == "font/woff2"
