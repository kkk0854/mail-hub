"""系统运维路由：版本检查、一键更新、OAuth 诊断、通知测试、系统信息。"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.db import get_db, utcnow
from ..models import Mailbox, Message, ParseAttempt, RegistrationTask
from ..services import notification_service
from .deps import client_ip, get_current_user

logger = logging.getLogger("mailhub.system")

router = APIRouter(prefix="/system", tags=["system"])


# ---------------------------------------------------------------- version / update
class UpdateTriggerIn(BaseModel):
    force: bool = False


@router.get("/version")
async def get_version():
    """当前版本信息。"""
    return {
        "current": settings.version,
        "app_name": settings.app_name,
        "debug": settings.debug,
        "embed_workers": settings.embed_workers,
        "database_url": settings.database_url.split("///")[-1] if "sqlite" in settings.database_url else "postgresql",
    }


@router.get("/update/check")
async def check_update(_: object = Depends(get_current_user)):
    """检查 GitHub 最新版本（需要配置 github_repo）。"""
    if not settings.github_repo or settings.github_repo == "your-org/mail-hub":
        return {"update_available": False, "current": settings.version, "latest": None, "message": "github_repo not configured"}
    try:
        url = f"https://api.github.com/repos/{settings.github_repo}/releases/latest"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return {"update_available": False, "current": settings.version, "latest": None,
                        "message": f"GitHub API returned {resp.status_code}"}
            data = resp.json()
            latest_tag = data.get("tag_name", "").lstrip("v")
            current = settings.version.lstrip("v").split("-")[0]
            update_available = _is_newer(latest_tag, current)
            return {
                "update_available": update_available,
                "current": settings.version,
                "latest": data.get("tag_name"),
                "release_notes": data.get("body", "")[:500],
                "published_at": data.get("published_at"),
                "html_url": data.get("html_url"),
            }
    except Exception as exc:
        logger.warning("check update error: %s", exc)
        return {"update_available": False, "current": settings.version, "latest": None, "message": str(exc)}


def _is_newer(latest: str, current: str) -> bool:
    """简单的语义化版本比较。"""
    try:
        l_parts = [int(x) for x in latest.split(".")[:3]]
        c_parts = [int(x) for x in current.split(".")[:3]]
        while len(l_parts) < 3:
            l_parts.append(0)
        while len(c_parts) < 3:
            c_parts.append(0)
        return tuple(l_parts) > tuple(c_parts)
    except Exception:
        return latest != current


@router.post("/update/trigger")
async def trigger_update(body: UpdateTriggerIn, _: object = Depends(get_current_user)):
    """触发 Watchtower 一键更新。"""
    if not settings.watchtower_api_token:
        raise HTTPException(400, "WATCHTOWER_HTTP_API_TOKEN not configured")
    try:
        url = f"{settings.watchtower_api_url}/v1/update"
        headers = {"Authorization": f"Bearer {settings.watchtower_api_token}"}
        params = {"force": "true"} if body.force else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, params=params)
            if resp.status_code in (200, 201):
                return {"triggered": True, "message": "update triggered, watchtower will pull and restart"}
            return {"triggered": False, "status_code": resp.status_code, "message": resp.text[:200]}
    except Exception as exc:
        logger.warning("trigger update error: %s", exc)
        raise HTTPException(502, f"watchtower connection failed: {exc}")


# ---------------------------------------------------------------- oauth diagnostics
class OAuthDiagnoseIn(BaseModel):
    refresh_token: str
    client_id: str = ""
    tenant: str = "consumers"
    scope: str = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All"


@router.post("/oauth/diagnose")
async def oauth_diagnose(body: OAuthDiagnoseIn, _: object = Depends(get_current_user)):
    """Outlook OAuth Token 诊断：验证 refresh_token 有效性，给出常见错误的解决方案。

    常见错误码与解决方案：
    - AADSTS9002331: 应用注册类型不对，应选择 "Accounts in any identity provider... and personal Microsoft accounts"
    - AADSTS70000: scope 未授权/失效，检查授权时 scope 和验证时 scope 是否一致，重新强制 Consent
    - AADSTS65001: 用户未授权，需要重新 Consent
    - AADSTS50058: 会话过期，需要重新登录授权
    - unauthorized_client: 应用未配置为 Public Client，或回调平台不对
    - invalid_client: client_id 错误或应用不存在
    """
    if not body.refresh_token:
        raise HTTPException(400, "refresh_token is required")

    token_url = f"https://login.microsoftonline.com/{body.tenant}/oauth2/v2.0/token"
    data = {
        "client_id": body.client_id or "00000000-0000-0000-0000-000000000000",
        "grant_type": "refresh_token",
        "refresh_token": body.refresh_token,
        "scope": body.scope,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code == 200:
                token_data = resp.json()
                # 解析 access_token 的 JWT payload（不验证签名，仅诊断）
                jwt_payload = _decode_jwt_payload(token_data.get("access_token", ""))
                return {
                    "valid": True,
                    "token_type": token_data.get("token_type"),
                    "expires_in": token_data.get("expires_in"),
                    "scope": token_data.get("scope"),
                    "jwt_aud": jwt_payload.get("aud"),
                    "jwt_iss": jwt_payload.get("iss"),
                    "jwt_tid": jwt_payload.get("tid"),
                    "jwt_preferred_username": jwt_payload.get("preferred_username"),
                    "jwt_scp": jwt_payload.get("scp"),
                    "message": "Token 有效，可以直接用于导入",
                }
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_code = error_data.get("error", "")
            error_subcode = error_data.get("error_codes", [])
            error_desc = error_data.get("error_description", "")[:300]
            guidance = _oauth_error_guidance(error_code, error_subcode)
            return {
                "valid": False,
                "status_code": resp.status_code,
                "error": error_code,
                "error_codes": error_subcode,
                "error_description": error_desc,
                "guidance": guidance,
            }
    except Exception as exc:
        logger.warning("oauth diagnose error: %s", exc)
        raise HTTPException(502, f"Microsoft token endpoint connection failed: {exc}")


def _decode_jwt_payload(token: str) -> dict:
    """简易 JWT payload 解码（不验证签名）。"""
    try:
        import base64
        import json

        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _oauth_error_guidance(error: str, error_codes: list[int]) -> str:
    """根据错误码给出解决方案指引。"""
    code = error_codes[0] if error_codes else 0
    if code == 9002331 or "9002331" in error:
        return ("错误：应用注册类型不对。\n"
                "解决：Azure 门户 → 应用注册 → 你的应用 → 清单(Manifest) → "
                "把 signInAudience 改为 'AzureADandPersonalMicrosoftAccount'，"
                "并确保 api.requestedAccessTokenVersion = 2。\n"
                "支持的账户类型应选择：任何组织目录中的账户和个人 Microsoft 账户。")
    if code == 70000 or "70000" in error:
        return ("错误：scope 未授权或已失效。\n"
                "解决：检查授权时使用的 scope 和验证时的 scope 是否一致；"
                "重新执行一次强制 Consent 授权（在授权 URL 中加 prompt=consent）。\n"
                "Graph 场景建议最小权限：offline_access + Mail.Read + User.Read；"
                "IMAP 场景额外加：Office 365 Exchange Online → IMAP.AccessAsUser.All。")
    if code == 65001 or "65001" in error:
        return ("错误：用户未授权该应用。\n"
                "解决：重新走授权流程，确保用户点击了接受按钮。"
                "如果是组织账号，可能需要管理员同意。")
    if code == 50058 or "50058" in error:
        return ("错误：用户会话已过期。\n"
                "解决：重新登录授权，获取新的 refresh_token。")
    if error == "unauthorized_client":
        return ("错误：应用未配置为 Public Client，或回调平台不对。\n"
                "解决：Azure 门户 → 应用注册 → 身份验证 → "
                "添加 '移动和桌面应用程序' 平台，重定向 URI 设为 http://localhost；"
                "并在 '身份验证' 页面底部启用 '允许公共客户端流'。\n"
                "不要使用 Web 平台的回调，否则 Azure 会视为机密客户端要求 client_secret。")
    if error == "invalid_client":
        return ("错误：client_id 错误或应用不存在。\n"
                "解决：检查 client_id 是否正确复制，应用是否已发布。")
    return ("未知错误。请检查：\n"
            "1. client_id 是否正确\n"
            "2. tenant 是否为 consumers（个人账号）或具体租户 ID（组织账号）\n"
            "3. refresh_token 是否过期（通常 90 天）\n"
            "4. 网络是否能访问 login.microsoftonline.com")


# ---------------------------------------------------------------- notification test
class NotifyTestIn(BaseModel):
    channel: str = "all"  # all / telegram / dingtalk / webhook
    title: str = "MAIL HUB 通知测试"
    body: str = "这是一条来自 MAIL HUB 的测试通知。如果你收到了，说明通知通道配置正确。"


@router.post("/notify/test")
async def notify_test(body: NotifyTestIn, request: Request, _: object = Depends(get_current_user)):
    """发送测试通知，验证通道配置。"""
    results = await notification_service.notify(body.title, body.body, event="test")
    return {"sent": results, "configured_channels": [c.name for c in notification_service.get_channels()]}


@router.get("/notify/channels")
async def notify_channels(_: object = Depends(get_current_user)):
    """查看已配置的通知通道（不返回密钥）。"""
    channels = []
    if settings.notify_telegram_bot_token:
        channels.append({"name": "telegram", "enabled": True,
                         "chat_id": settings.notify_telegram_chat_id,
                         "bot_token_masked": f"{settings.notify_telegram_bot_token[:6]}...{settings.notify_telegram_bot_token[-4:]}" if len(settings.notify_telegram_bot_token) > 10 else "***"})
    if settings.notify_dingtalk_webhook:
        channels.append({"name": "dingtalk", "enabled": True,
                         "webhook_masked": settings.notify_dingtalk_webhook[:40] + "..." if len(settings.notify_dingtalk_webhook) > 40 else settings.notify_dingtalk_webhook})
    if settings.notify_webhook_url:
        channels.append({"name": "webhook", "enabled": True,
                         "url_masked": settings.notify_webhook_url[:60] + "..." if len(settings.notify_webhook_url) > 60 else settings.notify_webhook_url})
    return {"channels": channels, "total": len(channels)}


# ---------------------------------------------------------------- stats / observability
@router.get("/stats/overview")
async def stats_overview(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    """系统概览统计（用于 Dashboard 数据大盘）。所有真实指标排除 is_demo 演示数据，另返回演示计数。"""
    from datetime import timedelta as _td

    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    NOT_DEMO = Mailbox.is_demo == False  # noqa: E712

    mailbox_count = (await session.execute(select(func.count(Mailbox.id)).where(NOT_DEMO))).scalar_one()
    healthy_count = (await session.execute(select(func.count(Mailbox.id)).where(NOT_DEMO, Mailbox.health_status == "HEALTHY"))).scalar_one()
    in_use_count = (await session.execute(select(func.count(Mailbox.id)).where(NOT_DEMO, Mailbox.status == "IN_USE"))).scalar_one()
    quarantined_count = (await session.execute(select(func.count(Mailbox.id)).where(NOT_DEMO, Mailbox.status == "QUARANTINED"))).scalar_one()
    demo_mailbox_count = (await session.execute(select(func.count(Mailbox.id)).where(Mailbox.is_demo == True))).scalar_one()  # noqa: E712

    task_total = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.is_demo == False))).scalar_one()  # noqa: E712
    task_today = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.is_demo == False, RegistrationTask.created_at >= today_start))).scalar_one()  # noqa: E712
    task_completed = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.is_demo == False, RegistrationTask.state == "COMPLETED"))).scalar_one()  # noqa: E712
    task_failed = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.is_demo == False, RegistrationTask.state.in_(("TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR", "CANCELLED"))))).scalar_one()  # noqa: E712
    task_in_flight = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.is_demo == False, RegistrationTask.state.in_(("WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED", "PARSING", "RESULT_READY", "WAITING_CALLBACK"))))).scalar_one()  # noqa: E712

    message_total = (await session.execute(select(func.count(Message.id)).where(Message.is_demo == False))).scalar_one()  # noqa: E712
    message_today = (await session.execute(select(func.count(Message.id)).where(Message.is_demo == False, Message.created_at >= today_start))).scalar_one()  # noqa: E712

    # 解析统计（最近 24 小时）
    day_ago = now - _td(hours=24)
    parse_total = (await session.execute(select(func.count(ParseAttempt.id)).where(ParseAttempt.is_demo == False, ParseAttempt.created_at >= day_ago))).scalar_one()  # noqa: E712
    parse_hit = (await session.execute(select(func.count(ParseAttempt.id)).where(ParseAttempt.is_demo == False, ParseAttempt.created_at >= day_ago, ParseAttempt.outcome == "HIT"))).scalar_one()  # noqa: E712
    parse_avg_confidence = (await session.execute(select(func.avg(ParseAttempt.confidence)).where(ParseAttempt.is_demo == False, ParseAttempt.created_at >= day_ago, ParseAttempt.outcome == "HIT"))).scalar_one() or 0  # noqa: E712
    parse_avg_duration = (await session.execute(select(func.avg(ParseAttempt.duration_ms)).where(ParseAttempt.is_demo == False, ParseAttempt.created_at >= day_ago))).scalar_one() or 0  # noqa: E712

    return {
        "mailboxes": {"total": mailbox_count, "healthy": healthy_count, "in_use": in_use_count, "quarantined": quarantined_count},
        "tasks": {"total": task_total, "today": task_today, "completed": task_completed, "failed": task_failed, "in_flight": task_in_flight,
                  "success_rate": round(task_completed / max(task_completed + task_failed, 1) * 100, 1)},
        "messages": {"total": message_total, "today": message_today},
        "parsing": {"total_24h": parse_total, "hit_24h": parse_hit, "hit_rate": round(parse_hit / max(parse_total, 1) * 100, 1),
                    "avg_confidence": round(parse_avg_confidence, 3), "avg_duration_ms": round(parse_avg_duration, 1)},
        "demo": {"mailboxes": demo_mailbox_count},
        "generated_at": now.isoformat(),
    }
