"""API v1 路由聚合（§16）。"""
from fastapi import APIRouter

from .routers_aliases import router as aliases
from .routers_audit import router as audit_logs, router_webhooks
from .routers_auth import router as auth
from .routers_dashboard import router as dashboard
from .routers_dev import router as dev
from .routers_domains import router as domains
from .routers_events import router as events
from .routers_fetch import router as fetch
from .routers_imports import router as imports
from .routers_inbound import router as inbound
from .routers_mailboxes import router as mailboxes
from .routers_messages import router as messages
from .routers_pools import router as pools
from .routers_registration import router as registration
from .routers_rules import router as rules
from .routers_system import router as system
from .routers_tempmail_providers import router as tempmail_providers

api_router = APIRouter()
api_router.include_router(auth)
api_router.include_router(mailboxes)
api_router.include_router(imports)
api_router.include_router(messages)
api_router.include_router(fetch)
api_router.include_router(aliases)
api_router.include_router(pools)
api_router.include_router(registration)
api_router.include_router(rules)
api_router.include_router(domains)
api_router.include_router(dashboard)
api_router.include_router(events)
api_router.include_router(inbound)
api_router.include_router(audit_logs)
api_router.include_router(router_webhooks)
api_router.include_router(system)
api_router.include_router(tempmail_providers)
api_router.include_router(dev)
