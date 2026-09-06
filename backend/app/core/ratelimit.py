"""简单的内存滑动窗口限流中间件（§20 API Rate Limit）。"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit_per_minute: int = 600):
        super().__init__(app)
        self.limit = limit_per_minute
        self._hits: dict[str, deque] = defaultdict(lambda: deque(maxlen=limit_per_minute * 2))

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            window = self._hits[ip]
            window.append(now)
            # 清理 60 秒以外的记录
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) > self.limit:
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)
