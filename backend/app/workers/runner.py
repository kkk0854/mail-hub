"""独立 Worker 进程入口：python -m app.workers.runner"""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main():
    from ..core.db import get_sessionmaker
    from ..models import Base
    from ..services.seed import seed
    from .scheduler import Scheduler

    engine_ok = get_sessionmaker()
    async with engine_ok() as session:
        await session.run_sync(lambda s: Base.metadata.create_all(s.bind))
        await seed(session)

    sched = Scheduler()
    sched.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await sched.stop()


if __name__ == "__main__":
    asyncio.run(main())
