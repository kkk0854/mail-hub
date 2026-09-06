"""API 依赖：JWT 用户认证 + API Key 认证（外部系统走 X-API-Key，§13/§20）。"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import security
from ..core.config import settings
from ..core.crypto import sha256_hex
from ..core.db import get_db
from ..models import ApiKey, User


async def _resolve_user(session: AsyncSession, auth_header: str, token: str | None) -> User | None:
    if not settings.auth_enabled:
        return (await session.execute(select(User).where(User.username == settings.admin_username))).scalar_one_or_none()
    raw = None
    if auth_header.startswith("Bearer "):
        raw = auth_header[7:].strip()
    elif token:
        raw = token
    if not raw:
        return None
    payload = security.decode_token(raw)
    if not payload:
        return None
    user = (await session.execute(select(User).where(User.username == payload.get("sub", "")))).scalar_one_or_none()
    return user if user and user.status == "active" else None


async def get_current_user_from_request(
    request: Request, session: AsyncSession = Depends(get_db)
) -> User | None:
    auth = request.headers.get("Authorization", "")
    return await _resolve_user(session, auth, request.query_params.get("token"))


async def get_current_user(user: User | None = Depends(get_current_user_from_request)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


async def get_current_user_or_key(
    request: Request,
    user: User | None = Depends(get_current_user_from_request),
    x_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    """控制台 JWT 或外部系统 API Key 二选一。"""
    if user is not None:
        return user
    if x_api_key:
        key_hash = sha256_hex(x_api_key)
        row = (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.status == "active"))
        ).scalar_one_or_none()
        if row:
            return User(id=f"apikey:{row.name}", username=f"apikey:{row.name}", password_hash="", role="api")
    raise HTTPException(status_code=401, detail="authentication required (JWT or X-API-Key)")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""
