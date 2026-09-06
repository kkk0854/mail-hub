"""Provider 注册表：类型 -> 适配器。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import MailProvider

PROVIDER_TYPES = ("outlook", "cloudflare", "imap", "simulator")


def get_provider_class(provider_type: str) -> type["MailProvider"]:
    if provider_type == "outlook":
        from .outlook_provider import OutlookProvider

        return OutlookProvider
    if provider_type == "cloudflare":
        from .cloudflare_provider import CloudflareProvider

        return CloudflareProvider
    if provider_type == "imap":
        from .imap_provider import ImapProvider

        return ImapProvider
    if provider_type == "simulator":
        from .simulator import SimulatorProvider

        return SimulatorProvider
    raise ValueError(f"unknown provider type: {provider_type}")


def create_provider(provider_type: str, mailbox, credentials: dict, config: dict) -> "MailProvider":
    cls = get_provider_class(provider_type)
    return cls(mailbox=mailbox, credentials=credentials, config=config)
