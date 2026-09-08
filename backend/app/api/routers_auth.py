from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import security
from ..core.config import DEFAULT_ADMIN_PASSWORD
from ..core.db import get_db, utcnow
from ..models import User
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import LoginIn

router = APIRouter(prefix="/auth", tags=["auth"])

# 登录防爆破：按 (IP, 用户名) 记录失败次数，超阈值锁定（MVP 内存实现；分布式部署建议换 Redis）
MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 900
_failed: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_FAILED_ATTEMPTS + 5))


def _lock_key(ip: str, username: str) -> str:
    return f"{ip}|{username.lower()}"


def _is_locked(ip: str, username: str) -> bool:
    q = _failed.get(_lock_key(ip, username))
    if not q or len(q) < MAX_FAILED_ATTEMPTS:
        return False
    return time.monotonic() - q[0] < LOCK_SECONDS


def _record_failure(ip: str, username: str) -> None:
    _failed[_lock_key(ip, username)].append(time.monotonic())


def _clear_failures(ip: str, username: str) -> None:
    _failed.pop(_lock_key(ip, username), None)


class LoginOut(BaseModel):
    token: str
    username: str
    role: str
    force_password_change: bool = False


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    username = body.username.strip()
    if _is_locked(ip, username):
        raise HTTPException(status_code=429, detail="too many login attempts, try again later")
    user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user or user.status != "active" or not security.verify_password(body.password, user.password_hash):
        _record_failure(ip, username)
        raise HTTPException(status_code=401, detail="invalid username or password")
    _clear_failures(ip, username)
    # 兜底：旧库升级后管理员仍使用内置默认口令 → 登录时补设强制改密标记（幂等）
    if user.force_password_change is not True and security.verify_password(DEFAULT_ADMIN_PASSWORD, user.password_hash):
        user.force_password_change = True
    token = security.create_access_token(user.username, user.role)
    user.updated_at = utcnow()
    await audit(session, "auth.login", resource_type="user", resource_id=user.id, ip=ip)
    await session.commit()
    return LoginOut(token=token, username=user.username, role=user.role, force_password_change=user.force_password_change)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "role": user.role,
        "id": user.id,
        "force_password_change": user.force_password_change,
    }


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """修改当前用户密码。初始管理员（仍为内置默认口令）必须先改密；改密后解除强制标记。"""
    if not security.verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="old password is incorrect")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="new password must differ from old password")
    weak = (
        len(body.new_password) < 8
        or not any(c.isalpha() for c in body.new_password)
        or not any(c.isdigit() for c in body.new_password)
    )
    if weak:
        raise HTTPException(status_code=400, detail="new password must be at least 8 chars, contain letters and digits")
    user.password_hash = security.hash_password(body.new_password)
    user.force_password_change = False
    user.updated_at = utcnow()
    await audit(session, "auth.change_password", resource_type="user", resource_id=user.id, ip="local")
    await session.commit()
    return {"ok": True, "username": user.username}
