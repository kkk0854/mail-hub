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


# 轻量迁移：为已存在的运行库补建复合索引（create_all 只建新表，不会修改已有表）。
INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_fetch_tasks_claim ON fetch_tasks (state, next_run_at)",
    "CREATE INDEX IF NOT EXISTS ix_fetch_tasks_mailbox_type_state ON fetch_tasks (mailbox_id, task_type, state)",
    "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_claim ON webhook_deliveries (state, next_run_at)",
    # v1.2.0
    "CREATE INDEX IF NOT EXISTS ix_temp_mail_provider_settings_name ON temp_mail_provider_settings (provider_name)",
    "CREATE INDEX IF NOT EXISTS ix_registration_tasks_project_key ON registration_tasks (project_key)",
    "CREATE INDEX IF NOT EXISTS ix_registration_tasks_claim_result ON registration_tasks (claim_result)",
    "CREATE INDEX IF NOT EXISTS ix_mailboxes_is_demo ON mailboxes (is_demo)",
    "CREATE INDEX IF NOT EXISTS ix_messages_is_demo ON messages (is_demo)",
)

# v1.2.0 轻量迁移：已有表补充新列（create_all 不会修改已有表）
# {表: [(列名, 列定义), ...]}
SCHEMA_UPGRADES: dict[str, list[tuple[str, str]]] = {
    "mailboxes": [
        ("is_alias", "BOOLEAN DEFAULT 0"),
        ("real_main_email", "VARCHAR(255)"),
        ("is_demo", "BOOLEAN DEFAULT 0"),
    ],
    "registration_tasks": [
        ("project_key", "VARCHAR(64)"),
        ("caller_id", "VARCHAR(64)"),
        ("claim_result", "VARCHAR(16)"),
        ("is_demo", "BOOLEAN DEFAULT 0"),
    ],
    "messages": [("is_demo", "BOOLEAN DEFAULT 0")],
    "parse_attempts": [("is_demo", "BOOLEAN DEFAULT 0")],
    "parse_results": [("is_demo", "BOOLEAN DEFAULT 0")],
    "mailbox_credentials": [("is_demo", "BOOLEAN DEFAULT 0")],
}


async def ensure_schema_updates() -> None:
    """为已存在的库补齐 v1.2.0 新增列（幂等，只加不删）。"""
    engine = get_engine()
    is_sqlite = "sqlite" in settings.database_url
    async with engine.begin() as conn:
        for table, columns in SCHEMA_UPGRADES.items():
            if is_sqlite:
                # PRAGMA table_info 获取现有列
                rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
                existing = {r[1] for r in rows}
            else:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :t"
                        ),
                        {"t": table},
                    )
                ).fetchall()
                existing = {r[0] for r in rows}
            for col, definition in columns:
                if col not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))


async def ensure_indexes() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        for ddl in INDEX_DDL:
            await conn.execute(text(ddl))
