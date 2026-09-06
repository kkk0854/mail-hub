"""邮件解析引擎（§11）：规则匹配 -> 提取 -> 加密存储 ParseResult。"""
from __future__ import annotations

import asyncio
import fnmatch
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.db import utcnow
from ..core.ids import new_id
from ..models import Message, ParseResult, ParserRule

OUTPUT_TYPES = ("OTP", "URL", "SECURITY_EVENT", "ORDER_ID", "ACTIVATION_LINK", "CUSTOM")


def match_sender(pattern: str, sender: str) -> bool:
    if not pattern or pattern.strip() in ("*", ""):
        return True
    pattern = pattern.strip().lower()
    sender = (sender or "").lower()
    return fnmatch.fnmatch(sender, pattern) or fnmatch.fnmatch(sender, f"*{pattern}*") or pattern in sender


def match_subject(pattern: str, subject: str) -> bool:
    if not pattern or not pattern.strip():
        return True
    try:
        return re.search(pattern, subject or "", re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in (subject or "").lower()


def category_for(result_types: list[str]) -> str:
    if any(t in ("OTP", "ACTIVATION_LINK") for t in result_types):
        return "verification"
    if "SECURITY_EVENT" in result_types:
        return "security"
    if "URL" in result_types:
        return "link"
    return "normal"


async def load_active_rules(session: AsyncSession, provider_type: str | None = None) -> list[ParserRule]:
    stmt = select(ParserRule).where(ParserRule.status == "active").order_by(ParserRule.priority.asc(), ParserRule.created_at.asc())
    rules = (await session.execute(stmt)).scalars().all()
    if provider_type:
        scoped = [r for r in rules if r.provider_type in (None, "", provider_type)]
        return scoped
    return list(rules)


def extract(rule: ParserRule, message: Message) -> tuple[bool, str, float]:
    """返回 (是否命中, 提取值, 置信度)。"""
    body = message.body_text or ""
    if rule.body_regex:
        try:
            m = re.search(rule.body_regex, body, re.IGNORECASE | re.MULTILINE)
        except re.error:
            return False, "", 0.0
        if not m:
            return False, "", 0.0
        value = m.group(1) if m.groups() else m.group(0)
        confidence = 0.99 if m.groups() else 0.9
        return True, value.strip(), confidence
    # 无 body_regex：仅按 sender/subject 命中（如安全事件通知）
    return True, (message.subject or "")[:200], 0.85


async def parse_message(session: AsyncSession, message: Message, provider_type: str | None = None) -> list[ParseResult]:
    """解析一封邮件。重复解析安全（先清空旧结果，§26.3 Message 与 ParseResult 分离）。"""
    results: list[ParseResult] = []
    old = (await session.execute(select(ParseResult).where(ParseResult.message_id == message.id))).scalars().all()
    for r in old:
        await session.delete(r)

    rules = await load_active_rules(session, provider_type)
    matched_types: list[str] = []
    for rule in rules:
        if not match_sender(rule.sender_pattern, message.sender):
            continue
        if not match_subject(rule.subject_pattern, message.subject):
            continue
        hit, value, confidence = extract(rule, message)
        if not hit or not value:
            continue
        results.append(
            ParseResult(
                id=new_id("pr"),
                message_id=message.id,
                rule_id=rule.id,
                rule_name=rule.name,
                result_type=rule.output_type,
                result_value_encrypted=crypto.encrypt_str(value),
                confidence=confidence,
                created_at=utcnow(),
            )
        )
        matched_types.append(rule.output_type)
        if len(results) >= 5:  # 单封邮件最多保留 5 个结果，避免噪音
            break

    for r in results:
        session.add(r)
    message.parse_status = "PARSED" if results else "NO_MATCH"
    message.category = category_for(matched_types)
    return results


def decrypt_result(result: ParseResult) -> dict:
    return {
        "id": result.id,
        "message_id": result.message_id,
        "rule_id": result.rule_id,
        "rule_name": result.rule_name,
        "type": result.result_type,
        "value": crypto.decrypt_str(result.result_value_encrypted),
        "confidence": result.confidence,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }
