"""测试公共设施：独立临时数据库 + ASGI 客户端。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_TMP = tempfile.mkdtemp(prefix="mailhub-test-")
os.environ["MAILHUB_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.replace(chr(92), '/')}/test.db"
os.environ["MAILHUB_EMBED_WORKERS"] = "false"
os.environ["MAILHUB_AUTH_ENABLED"] = "true"
os.environ["MAILHUB_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["MAILHUB_SYNC_INTERVAL_SECONDS"] = "3600"
os.environ["MAILHUB_HEALTH_CHECK_INTERVAL_SECONDS"] = "3600"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.seed import seed  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session", autouse=True)
async def _init_db():
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.run_sync(lambda s: Base.metadata.create_all(s.bind))
        await seed(session)
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture(scope="session")
async def admin_token(_init_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(f"{API}/auth/login", json={"username": settings.admin_username, "password": settings.admin_password})
        assert resp.status_code == 200, resp.text
        return resp.json()["token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def api_key():
    return settings.api_key
