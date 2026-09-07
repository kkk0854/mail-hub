"""LLM 验证码兜底提取服务（v1.2.0）。

触发策略：规则引擎解析结果置信度低于阈值时，调用 LLM 二次提取。
- 固定 JSON 输出契约：{"code": "", "link": "", "confidence": 0-1}
- 熔断保护：连续失败 N 次（默认 5）自动临时关闭兜底，避免无效 API 开销
- 支持 OpenAI 兼容接口（/chat/completions）
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from ..core.config import settings

logger = logging.getLogger("mailhub.llm")

# 熔断状态（进程内）
_consecutive_failures = 0
_circuit_open = False


def llm_enabled() -> bool:
    """兜底是否可用：开关 + API Key 配置 + 熔断未打开。"""
    return (
        settings.llm_fallback_enable
        and bool(settings.llm_api_key)
        and not _circuit_open
    )


def is_circuit_open() -> bool:
    return _circuit_open


def circuit_failures() -> int:
    return _consecutive_failures


def _extract_json(text: str) -> dict | None:
    """从 LLM 回复中提取 JSON（容忍 markdown 代码块包裹）。"""
    if not text:
        return None
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取第一个 { ... } 块
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


LLM_PROMPT = """你是一个邮件验证码提取器。从下面的邮件原文中提取验证码（OTP）和激活链接。
规则：
- 验证码通常是 4-8 位数字或字母数字组合
- 激活链接是 http(s):// 开头的 URL
- 邮件中没有相关内容时，对应字段返回空字符串
- 置信度 confidence 取 0.0-1.0，表示你对提取结果的把握

只输出 JSON，不要输出其他文字：
{"code": "验证码或空字符串", "link": "激活链接或空字符串", "confidence": 0.0-1.0}

邮件原文：
{sender_line}
{subject_line}
{body}
"""


def _build_prompt(*, sender: str, subject: str, body: str) -> str:
    """构造提示词。使用 replace 而非 format，避免邮件正文含 {} 导致崩溃。"""
    return (
        LLM_PROMPT.replace("{sender_line}", f"发件人：{sender}")
        .replace("{subject_line}", f"主题：{subject}")
        .replace("{body}", body)
    )


async def llm_extract(
    *,
    sender: str,
    subject: str,
    body: str,
) -> dict | None:
    """调用 LLM 提取验证码/链接。返回 {"code", "link", "confidence"} 或 None（失败）。"""
    global _consecutive_failures, _circuit_open

    if not llm_enabled():
        return None

    if len(body or "") > 6000:
        body = (body or "")[:6000] + "\n...（原文过长已截断）"

    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": "你是邮件验证码提取器，严格按 JSON 输出。",
            },
            {
                "role": "user",
                "content": _build_prompt(sender=sender or "", subject=subject or "", body=body or ""),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 200,
    }

    base = settings.llm_api_base.rstrip("/")
    url = f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm_api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_fallback_timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 400 and "response_format" in str(resp.text):
                # 部分 OpenAI 兼容 API 不支持 response_format，去掉后重试一次
                payload.pop("response_format", None)
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("llm fallback HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        if parsed is None:
            logger.warning("llm fallback: cannot parse response %r", content[:200])
            return None

        # 规范化输出
        code = str(parsed.get("code") or "").strip()
        link = str(parsed.get("link") or "").strip()
        try:
            confidence = float(parsed.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        if not code and not link:
            # 正常"未命中"，不算失败
            _consecutive_failures = 0
            return {"code": "", "link": "", "confidence": confidence, "matched": False}

        _consecutive_failures = 0
        return {"code": code, "link": link, "confidence": confidence, "matched": True}
    except Exception as exc:
        _consecutive_failures += 1
        logger.warning("llm fallback error (%d/%d): %s", _consecutive_failures, settings.llm_max_consecutive_failures, exc)
        if _consecutive_failures >= settings.llm_max_consecutive_failures:
            _circuit_open = True
            logger.error("llm fallback circuit opened after %d consecutive failures", _consecutive_failures)
        return None
