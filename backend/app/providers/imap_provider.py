"""标准 IMAP Provider（IMAP4_SSL，UID 增量同步）。凭据：IMAP_HOST / IMAP_PORT / IMAP_USER / PASSWORD。"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime

from .base import HealthCheckResult, MailProvider, ProviderError, SyncedMessage

logger = logging.getLogger("mailhub.provider.imap")


def _decode(value) -> str:
    if value is None:
        return ""
    parts = decode_header(str(value))
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    text_body, html_body = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if ctype == "text/plain" and not text_body:
                text_body = content
            elif ctype == "text/html" and not html_body:
                html_body = content
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = content
            else:
                text_body = content
    return text_body, html_body


def parse_raw_message(raw: bytes, provider_message_id: str) -> SyncedMessage:
    msg = email.message_from_bytes(raw)
    sender = _decode(msg.get("From"))
    realname, addr = (getaddresses([sender]) or [(None, "")])[0]
    recipient = _decode(msg.get("To"))
    received_at = None
    try:
        if msg.get("Date"):
            received_at = parsedate_to_datetime(msg.get("Date"))
            if received_at.tzinfo is not None:
                received_at = received_at.astimezone().replace(tzinfo=None)
    except Exception:
        received_at = None
    text_body, html_body = _extract_body(msg)
    headers = {k: _decode(v) for k, v in msg.items() if k.lower() in ("message-id", "thread-id", "in-reply-to", "x-mailer")}
    return SyncedMessage(
        provider_message_id=provider_message_id or (msg.get("Message-ID") or "").strip() or f"raw-{abs(hash(raw))}",
        sender=addr or sender,
        recipient=recipient,
        subject=_decode(msg.get("Subject")),
        text_body=text_body,
        html_body=html_body,
        headers=headers,
        received_at=received_at,
        raw=raw,
    )


class ImapProvider(MailProvider):
    type = "imap"

    def _conn_params(self) -> tuple[str, int, str, str]:
        host = self.credentials.get("IMAP_HOST") or (self.mailbox.metadata_json or {}).get("imap_host", "")
        port = int(self.credentials.get("IMAP_PORT") or (self.mailbox.metadata_json or {}).get("imap_port") or 993)
        user = self.credentials.get("IMAP_USER") or self.mailbox.email
        password = self.credentials.get("PASSWORD") or ""
        if not host:
            raise ProviderError("IMAP host not configured", "CONFIG_MISSING")
        return host, port, user, password

    def _connect(self) -> imaplib.IMAP4:
        host, port, user, password = self._conn_params()
        conn = imaplib.IMAP4_SSL(host, port) if port == 993 else imaplib.IMAP4(host, port)
        conn.login(user, password)
        return conn

    async def test_connection(self) -> HealthCheckResult:
        result = HealthCheckResult()
        try:
            conn = await asyncio.to_thread(self._connect)
            result.connectivity = True
            result.authorization = True
            status, _ = await asyncio.to_thread(conn.select, "INBOX")
            result.fetch = status == "OK"
            result.sync = True
            await asyncio.to_thread(conn.logout)
            result.details["folders"] = ["INBOX"]
        except ProviderError:
            raise
        except imaplib.IMAP4.error as exc:
            result.connectivity = True
            result.authorization = False
            result.fetch = False
            result.sync = False
            result.auth_error_code = "AUTH_FAILED"
            result.details["error"] = str(exc)
        except Exception as exc:
            result.connectivity = False
            result.authorization = False
            result.fetch = False
            result.sync = False
            result.details["error"] = f"{type(exc).__name__}: {exc}"
        return result

    async def sync_incremental(self, cursor: dict) -> tuple[list[SyncedMessage], dict]:
        cursor = dict(cursor or {})
        last_uid = int(cursor.get("last_uid") or 0)
        host, port, user, password = self._conn_params()

        def _do_sync():
            conn = self._connect()
            try:
                conn.select("INBOX", readonly=True)
                status, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
                if status != "OK":
                    return [], last_uid
                uids = [int(u) for u in (data[0] or b"").split() if int(u) > last_uid]
                messages = []
                max_uid = last_uid
                for uid in uids[-100:]:  # 单次最多 100 封，避免超长任务
                    st, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
                    if st != "OK" or not msg_data or msg_data[0] is None:
                        continue
                    raw = msg_data[0][1]
                    messages.append(parse_raw_message(raw, f"uid-{uid}"))
                    max_uid = max(max_uid, uid)
                return messages, max_uid
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        try:
            messages, max_uid = await asyncio.to_thread(_do_sync)
        except imaplib.IMAP4.error as exc:
            raise ProviderError(str(exc), "IMAP_ERROR") from exc
        new_cursor = dict(cursor)
        new_cursor["last_uid"] = max_uid
        return messages, new_cursor

    async def list_folders(self) -> list[str]:
        conn = await asyncio.to_thread(self._connect)
        try:
            status, folders = await asyncio.to_thread(conn.list)
            if status != "OK":
                return ["INBOX"]
            return [f.decode("utf-8", "replace").rsplit('"', 2)[-2] for f in folders if f]
        finally:
            try:
                await asyncio.to_thread(conn.logout)
            except Exception:
                pass
