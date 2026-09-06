"""MAIL HUB — 多邮箱接入、注册任务编排与自动取件回填平台。

MVP: FastAPI + SQLite(WAL) + 内嵌 Worker + SSE。生产可切换 PostgreSQL/Redis（§4）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .core.config import settings
from .core.db import check_db_connection, ensure_indexes, get_engine, get_sessionmaker
from .core.ratelimit import RateLimitMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# 日志脱敏：Token / Authorization 不落日志（§20）
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class SensitiveFilter(logging.Filter):
    PATTERNS = ("authorization", "bearer ", "refresh_token", "access_token", "api_key")
    REDACTION = "***REDACTED***"

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            lowered = msg.lower()
            for p in self.PATTERNS:
                if p in lowered:
                    record.msg = self.REDACTION
                    record.args = None
                    break
        except Exception:
            pass
        return True


for name in ("mailhub", "uvicorn.error"):
    logging.getLogger(name).addFilter(SensitiveFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .models import Base
    from .services.seed import seed

    get_engine()
    async with get_sessionmaker()() as session:
        await session.run_sync(lambda s: Base.metadata.create_all(s.bind))
        await seed(session)
    await ensure_indexes()
    logging.getLogger("mailhub").info("database ready (%s)", settings.database_url.split("///")[-1])

    scheduler = None
    if settings.embed_workers:
        from .workers.scheduler import scheduler as sched

        sched.start()
        scheduler = sched
    yield
    if scheduler:
        await scheduler.stop()


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan, docs_url="/docs", openapi_url="/openapi.json")

app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    # 不记录任何 header（可能包含 Authorization，§20）
    response = await call_next(request)
    logging.getLogger("mailhub.api").debug("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok", "db": await check_db_connection(), "version": settings.version}


app.include_router(api_router, prefix="/api/v1")

# ---------------------------------------------------------------- static (frontend build)
STATIC_DIR = Path(settings.static_dir).resolve()
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "docs", "openapi.json", "healthz")):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(STATIC_DIR / "index.html"))
