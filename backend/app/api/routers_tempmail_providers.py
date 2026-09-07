"""临时邮箱 Provider 插件管理路由（v1.2.0 插件化）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db, utcnow
from ..models import TempMailProviderSetting
from ..providers.provider_manager import ProviderManager
from ..services.audit import audit
from .deps import get_current_user
from .schemas import TempMailProviderIn

logger = logging.getLogger("mailhub.tempmail.api")

router = APIRouter(prefix="/tempmail-providers", tags=["tempmail-providers"])

# 配置脱敏：字段名含这些关键字视为敏感，不向客户端返回明文
SECRET_HINT = ("key", "token", "secret", "password", "authorization", "cookie", "header")
MASK = "******"


def _is_secret_field(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in SECRET_HINT)


def _mask_config(config: dict) -> dict:
    """对敏感配置字段打码后再返回前端。"""
    out = {}
    for k, v in (config or {}).items():
        out[k] = MASK if (v and _is_secret_field(k)) else v
    return out


def _merge_masked_config(old: dict, new: dict) -> dict:
    """合并前端提交的配置：掩码值（******）表示未修改，保留 DB 原值。"""
    merged = dict(old or {})
    for k, v in (new or {}).items():
        if v == MASK:
            continue  # 未修改
        merged[k] = v
    return merged


def _setting_out(s: TempMailProviderSetting | None, meta: dict) -> dict:
    return {
        "name": meta["name"],
        "display_name": meta["display_name"],
        "requires_config": meta["requires_config"],
        "enabled": s.enabled if s else False,
        "priority": s.priority if s else meta.get("default_priority", 100),
        "config": _mask_config(s.config_json) if s else {},
        "configured": bool((s.config_json or {}) if s else False),
    }


@router.get("")
async def list_providers(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    """列出全部已注册的临时邮箱 Provider 及其启用状态/配置。"""
    rows = (await session.execute(select(TempMailProviderSetting))).scalars().all()
    settings = {s.provider_name: s for s in rows}
    out = []
    for meta in ProviderManager.list():
        out.append(_setting_out(settings.get(meta["name"]), meta))
    return {"items": out, "total": len(out)}


@router.get("/{name}/schema")
async def get_schema(name: str, _: object = Depends(get_current_user)):
    """获取指定 Provider 的配置表单 Schema。"""
    cls = ProviderManager.get(name)
    if not cls:
        raise HTTPException(404, f"unknown tempmail provider: {name}")
    return {"name": name, "display_name": cls.display_name, "schema": cls.get_config_schema(cls)}


@router.put("/{name}")
async def update_provider(
    name: str,
    body: TempMailProviderIn,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    """更新 Provider 启用状态、优先级、配置。"""
    cls = ProviderManager.get(name)
    if not cls:
        raise HTTPException(404, f"unknown tempmail provider: {name}")

    setting = (
        await session.execute(select(TempMailProviderSetting).where(TempMailProviderSetting.provider_name == name))
    ).scalar_one_or_none()
    now = utcnow()

    # 掩码合并：前端回传的 ****** 字段保留原值
    merged_config = _merge_masked_config(setting.config_json if setting else {}, body.config)

    # 配置校验（合并后校验，避免掩码覆盖导致误判）
    if body.enabled and merged_config:
        valid, err = cls.validate_config(cls, merged_config)
        if not valid:
            raise HTTPException(400, f"config invalid: {err}")

    if setting is None:
        setting = TempMailProviderSetting(
            provider_name=name,
            enabled=body.enabled,
            priority=body.priority,
            config_json=merged_config,
            created_at=now,
            updated_at=now,
        )
        session.add(setting)
    else:
        setting.enabled = body.enabled
        setting.priority = body.priority
        setting.config_json = merged_config
        setting.updated_at = now

    await audit(
        session, "tempmail_provider.update", resource_type="tempmail_provider", resource_id=name,
        actor_type="user", metadata={"enabled": body.enabled, "priority": body.priority},
    )
    await session.commit()
    return _setting_out(setting, {"name": name, "display_name": cls.display_name, "requires_config": cls.requires_config})


@router.post("/{name}/test")
async def test_provider(name: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    """连通性测试：用已保存配置实际申请一个临时邮箱并立即释放，验证 Provider 可用。"""
    cls = ProviderManager.get(name)
    if not cls:
        raise HTTPException(404, f"unknown tempmail provider: {name}")

    setting = (
        await session.execute(select(TempMailProviderSetting).where(TempMailProviderSetting.provider_name == name))
    ).scalar_one_or_none()
    config = setting.config_json if setting else {}
    valid, err = cls.validate_config(cls, config)
    if not valid:
        raise HTTPException(400, f"config invalid: {err}")

    provider = cls(config)
    try:
        created = await provider.create_email()
        email = created.get("email") or ""
        cleanup = ""
        if email:
            try:
                await provider.delete_email(email, created.get("password"))
                cleanup = "ok"
            except Exception as exc:  # 释放失败不阻断测试结果，但记录
                cleanup = f"cleanup_failed: {exc}"
        await audit(session, "tempmail_provider.test", resource_type="tempmail_provider", resource_id=name,
                    actor_type="user", metadata={"ok": True, "email": email})
        await session.commit()
        return {"ok": True, "email": email, "cleanup": cleanup}
    except Exception as exc:
        await audit(session, "tempmail_provider.test", resource_type="tempmail_provider", resource_id=name,
                    actor_type="user", metadata={"ok": False, "error": str(exc)[:300]})
        await session.commit()
        return {"ok": False, "error": str(exc)}


@router.get("/dispatch/order")
async def dispatch_order(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    """返回按优先级排序的可用于动态创建临时邮箱的 Provider 列表（仅 enabled + 已配置）。"""
    rows = (await session.execute(select(TempMailProviderSetting).where(TempMailProviderSetting.enabled == True))).scalars().all()  # noqa: E712
    settings = {s.provider_name: s for s in rows}
    order = []
    for meta in ProviderManager.list():
        s = settings.get(meta["name"])
        if s is None:
            continue
        cls = ProviderManager.get(meta["name"])
        valid, _ = cls.validate_config(cls, s.config_json or {}) if cls else (False, "unknown")
        if not valid:
            continue
        order.append({"name": meta["name"], "display_name": meta["display_name"], "priority": s.priority})
    order.sort(key=lambda x: x["priority"])
    return {"order": order}
