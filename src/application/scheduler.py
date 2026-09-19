"""Cron scheduler for independently configured sources."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.sources import SourceCatalog

from .runner import PipelineRunner

LOGGER = logging.getLogger(__name__)


def build_scheduler(
    runner: PipelineRunner,
    catalog: SourceCatalog,
    *,
    timezone: str = "UTC",
) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=timezone)
    registered = set(runner.registry.ids())
    for source in catalog.sources:
        if source.source_id not in registered or not source.schedule:
            continue
        scheduler.add_job(
            runner.run,
            trigger=CronTrigger.from_crontab(source.schedule, timezone=timezone),
            id=f"source:{source.source_id}",
            name=f"Collect {source.name}",
            kwargs={"source_id": source.source_id},
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
            replace_existing=True,
        )
        LOGGER.info("Scheduled %s with %s", source.source_id, source.schedule)
    if runner.notifications:
        scheduler.add_job(
            runner.dispatch_notifications,
            trigger="interval",
            minutes=1,
            id="notifications:pending",
            name="Deliver pending notifications",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
    if not scheduler.get_jobs():
        raise ValueError("no active sources have a schedule")
    return scheduler
