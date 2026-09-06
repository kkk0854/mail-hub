"""SSE 实时事件流（§18）。EventSource 用 query token 认证。"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..core import security
from ..core.events import bus, recent_events
from ..core.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/events", tags=["events"])

KEEPALIVE_SECONDS = 15


async def _event_stream(token: str):
    payload = security.decode_token(token) if token else None
    if not payload:
        raise HTTPException(401, "invalid token")

    queue = bus.subscribe()
    try:
        # 先回放最近事件（取件中心刷新后仍可见）；统一用匿名消息便于 EventSource.onmessage 接收
        for event in await recent_events(limit=80):
            yield f"id: {event['event_id']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        while True:
            try:
                record = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"id: {record['event_id']}\ndata: {json.dumps(record, ensure_ascii=False, default=str)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        bus.unsubscribe(queue)


@router.get("/stream")
async def stream(token: str = Query(default="")):
    return StreamingResponse(
        _event_stream(token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
