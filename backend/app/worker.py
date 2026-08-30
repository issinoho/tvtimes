"""arq worker entrypoint.

Run with: ``arq app.worker.WorkerSettings``

Task functions are registered per phase (refresh_source, refresh_epg,
enrich_programme). For now the worker starts cleanly with no jobs so the dev
stack is complete.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.logging import configure_logging, get_logger


async def startup(_ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.is_prod)
    get_logger("worker").info("worker.startup", env=settings.env)


async def shutdown(_ctx: dict[str, Any]) -> None:
    get_logger("worker").info("worker.shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
