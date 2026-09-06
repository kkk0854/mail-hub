"""数据库初始化。MVP 使用 SQLite(WAL)；生产切换 PostgreSQL 只需改 DATABASE_URL。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def utcnow() -> datetime:
    """统一使用 naive UTC 存储。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False, future=True)

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_db():
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_db_connection() -> bool:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
