"""统一通知服务：Telegram / 钉钉 / Webhook 多通道抽象。

配置通过环境变量注入（MAILHUB_NOTIFY_*），也可在设置页动态配置（存入 providers 表的 config_encrypted）。
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from ..core.config import settings

logger = logging.getLogger("mailhub.notify")


class NotificationChannel(Protocol):
    name: str

    async def send(self, title: str, body: str, **kwargs) -> bool: ...


class TelegramChannel:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send(self, title: str, body: str, **kwargs) -> bool:
        if not self.bot_token or not self.chat_id:
            return False
        text = f"<b>{title}</b>\n\n{body}"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                ok = resp.status_code == 200 and resp.json().get("ok", False)
                if not ok:
                    logger.warning("telegram send failed: %s", resp.text[:200])
                return ok
        except Exception as exc:
            logger.warning("telegram send error: %s", exc)
            return False


class DingTalkChannel:
    name = "dingtalk"

    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    async def send(self, title: str, body: str, **kwargs) -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"### {title}\n\n{body}"},
        }
        url = self.webhook_url
        if self.secret:
            import hashlib
            import hmac
            import time
            import urllib.parse

            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{self.secret}"
            hmac_code = hmac.new(self.secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(hmac_code)
            url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                ok = resp.status_code == 200 and resp.json().get("errcode", -1) == 0
                if not ok:
                    logger.warning("dingtalk send failed: %s", resp.text[:200])
                return ok
        except Exception as exc:
            logger.warning("dingtalk send error: %s", exc)
            return False


class WebhookChannel:
    """通用 Webhook 通知（POST JSON）。"""
    name = "webhook"

    def __init__(self, url: str, secret: str = ""):
        self.url = url
        self.secret = secret

    async def send(self, title: str, body: str, **kwargs) -> bool:
        if not self.url:
            return False
        payload = {"title": title, "body": body, "event": kwargs.get("event", ""), "data": kwargs.get("data", {})}
        headers = {"Content-Type": "application/json"}
        if self.secret:
            import hashlib
            import hmac
            import json
            import time

            timestamp = str(int(time.time()))
            body_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            signature = hmac.new(self.secret.encode(), f"{timestamp}.{body_str}".encode(), hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={signature}"
            headers["X-Timestamp"] = timestamp
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self.url, json=payload, headers=headers)
                return 200 <= resp.status_code < 300
        except Exception as exc:
            logger.warning("webhook notify error: %s", exc)
            return False


def get_channels() -> list[NotificationChannel]:
    """从配置构建通知通道列表。"""
    channels: list[NotificationChannel] = []
    if settings.notify_telegram_bot_token and settings.notify_telegram_chat_id:
        channels.append(TelegramChannel(settings.notify_telegram_bot_token, settings.notify_telegram_chat_id))
    if settings.notify_dingtalk_webhook:
        channels.append(DingTalkChannel(settings.notify_dingtalk_webhook, settings.notify_dingtalk_secret))
    if settings.notify_webhook_url:
        channels.append(WebhookChannel(settings.notify_webhook_url, settings.notify_webhook_secret))
    return channels


async def notify(title: str, body: str, **kwargs) -> dict[str, bool]:
    """向所有已配置通道发送通知。返回 {channel_name: success}。"""
    channels = get_channels()
    if not channels:
        logger.debug("no notification channels configured, skip: %s", title)
        return {}
    results: dict[str, bool] = {}
    for ch in channels:
        try:
            results[ch.name] = await ch.send(title, body, **kwargs)
        except Exception as exc:
            logger.warning("notify channel %s error: %s", ch.name, exc)
            results[ch.name] = False
    return results


async def notify_verification(mailbox_email: str, result_type: str, result_value: str, sender: str = "", subject: str = "") -> None:
    """验证码/链接提取成功通知。"""
    title = "📬 新验证码提取成功"
    body = (
        f"邮箱：`{mailbox_email}`\n"
        f"类型：{result_type}\n"
        f"结果：`{result_value}`\n"
        f"发件人：{sender}\n"
        f"主题：{subject}"
    )
    await notify(title, body, event="verification_extracted", data={
        "mailbox": mailbox_email, "type": result_type, "value": result_value,
    })


async def notify_task_completed(task_id: str, external_ref: str, mailbox_email: str, result_type: str, result_value: str) -> None:
    """注册任务完成通知。"""
    title = "✅ 注册任务完成"
    body = (
        f"任务ID：`{task_id}`\n"
        f"外部引用：{external_ref}\n"
        f"邮箱：`{mailbox_email}`\n"
        f"结果类型：{result_type}\n"
        f"结果值：`{result_value}`"
    )
    await notify(title, body, event="task_completed", data={
        "task_id": task_id, "external_ref": external_ref, "mailbox": mailbox_email,
    })


async def notify_health_alert(mailbox_email: str, health_status: str, error: str = "") -> None:
    """邮箱健康告警通知。"""
    title = "⚠️ 邮箱健康告警"
    body = f"邮箱：`{mailbox_email}`\n状态：{health_status}\n错误：{error}"
    await notify(title, body, event="health_alert", data={"mailbox": mailbox_email, "status": health_status})
