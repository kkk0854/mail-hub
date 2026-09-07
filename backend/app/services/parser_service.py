"""邮件解析引擎（§11）：规则匹配 -> 提取 -> 加密存储 ParseResult。"""
from __future__ import annotations

import asyncio
import fnmatch
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.config import settings
from ..core.db import utcnow
from ..core.ids import new_id
from ..models import Message, ParseAttempt, ParseResult, ParserRule

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
        rule_start = time.perf_counter()
        outcome = "NO_MATCH"
        error_msg = ""
        confidence = 0.0
        value = ""
        try:
            if not match_sender(rule.sender_pattern, message.sender):
                outcome = "NO_MATCH"
            elif not match_subject(rule.subject_pattern, message.subject):
                outcome = "NO_MATCH"
            else:
                hit, value, confidence = extract(rule, message)
                if not hit or not value:
                    outcome = "NO_MATCH"
                else:
                    outcome = "HIT"
        except Exception as exc:
            outcome = "REGEX_ERROR"
            error_msg = str(exc)[:200]

        duration_ms = int((time.perf_counter() - rule_start) * 1000)
        # 记录每条规则的解析尝试（可观测性）
        session.add(ParseAttempt(
            id=new_id("pa"),
            message_id=message.id,
            mailbox_id=message.mailbox_id,
            rule_id=rule.id,
            rule_name=rule.name,
            provider_type=provider_type,
            outcome=outcome,
            output_type=rule.output_type if outcome == "HIT" else "",
            confidence=confidence,
            duration_ms=duration_ms,
            error=error_msg,
            created_at=utcnow(),
        ))

        if outcome != "HIT":
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

    # v1.2.0: LLM 兜底——规则结果置信度低于阈值时，尝试 LLM 二次提取
    if not results or max((x.confidence for x in results), default=0) < settings.llm_confidence_threshold:
        await _maybe_llm_fallback(session, message, results, provider_type)

    return results


async def _maybe_llm_fallback(
    session: AsyncSession, message: Message, results: list[ParseResult], provider_type: str | None
) -> None:
    """低置信/未命中时调用 LLM 兜底提取。"""
    from . import llm_fallback

    if not llm_fallback.llm_enabled():
        return

    start = time.perf_counter()
    outcome = await llm_fallback.llm_extract(
        sender=message.sender,
        subject=message.subject,
        body=message.body_text or "",
    )
    duration_ms = int((time.perf_counter() - start) * 1000)

    if outcome is None:
        session.add(ParseAttempt(
            id=new_id("pa"),
            message_id=message.id,
            mailbox_id=message.mailbox_id,
            rule_id=None,
            rule_name="llm_fallback",
            provider_type=provider_type,
            outcome="LLM_ERROR",
            output_type="",
            confidence=0.0,
            duration_ms=duration_ms,
            error="llm call failed",
            created_at=utcnow(),
        ))
        return

    if not outcome.get("matched"):
        session.add(ParseAttempt(
            id=new_id("pa"),
            message_id=message.id,
            mailbox_id=message.mailbox_id,
            rule_id=None,
            rule_name="llm_fallback",
            provider_type=provider_type,
            outcome="NO_MATCH",
            output_type="",
            confidence=float(outcome.get("confidence") or 0),
            duration_ms=duration_ms,
            error="",
            created_at=utcnow(),
        ))
        return

    # LLM 命中：写入 ParseResult（与已有结果去重）
    code = outcome.get("code") or ""
    link = outcome.get("link") or ""
    confidence = float(outcome.get("confidence") or 0)

    if code:
        existing_values = {crypto.decrypt_str(r.result_value_encrypted) for r in results}
        if code not in existing_values:
            results.append(ParseResult(
                id=new_id("pr"),
                message_id=message.id,
                rule_id=None,
                rule_name="llm_fallback",
                result_type="OTP" if _looks_like_otp(code) else "CUSTOM",
                result_value_encrypted=crypto.encrypt_str(code),
                confidence=confidence,
                created_at=utcnow(),
            ))
    if link:
        existing_values = {crypto.decrypt_str(r.result_value_encrypted) for r in results}
        if link not in existing_values:
            results.append(ParseResult(
                id=new_id("pr"),
                message_id=message.id,
                rule_id=None,
                rule_name="llm_fallback",
                result_type="ACTIVATION_LINK",
                result_value_encrypted=crypto.encrypt_str(link),
                confidence=confidence,
                created_at=utcnow(),
            ))

    for r in results:
        session.add(r)
    message.parse_status = "PARSED" if results else message.parse_status
    message.category = category_for([x.result_type for x in results]) if results else message.category

    session.add(ParseAttempt(
        id=new_id("pa"),
        message_id=message.id,
        mailbox_id=message.mailbox_id,
        rule_id=None,
        rule_name="llm_fallback",
        provider_type=provider_type,
        outcome="HIT",
        output_type=",".join(sorted({r.result_type for r in results if r.rule_id is None})),
        confidence=confidence,
        duration_ms=duration_ms,
        error="",
        created_at=utcnow(),
    ))


def _looks_like_otp(value: str) -> bool:
    """启发式判断是否为 OTP（4-8 位数字，或含字母的短验证码）。"""
    value = value.strip()
    if not value:
        return False
    if value.isdigit() and 4 <= len(value) <= 8:
        return True
    # 常见验证码格式：混合字母数字 4-10 位（不含空格）
    if re.fullmatch(r"[A-Za-z0-9]{4,10}", value):
        return True
    return False


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
