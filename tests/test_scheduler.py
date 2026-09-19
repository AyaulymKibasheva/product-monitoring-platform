from pathlib import Path

from src.application import PipelineRunner
from src.application.scheduler import build_scheduler
from src.models import Organization, SourceDefinition, SourceType
from src.sources import ProductSource, SourceCatalog, SourceRegistry, SourceRunResult, SourceRunStats


class ScheduledSource(ProductSource):
    organization_id = "org"
    source_id = "scheduled"

    def collect(self, *, max_pages=None):
        return SourceRunResult("org", "scheduled", [], SourceRunStats())


def test_builds_cron_job_for_scheduled_active_source(tmp_path: Path) -> None:
    catalog = SourceCatalog(
        organizations=(Organization("org", "Organization"),),
        sources=(
            SourceDefinition(
                "scheduled",
                "org",
                "Scheduled",
                SourceType.API,
                "fake",
                schedule="*/15 * * * *",
            ),
        ),
    )
    runner = PipelineRunner(
        SourceRegistry([ScheduledSource()]), catalog, output_directory=tmp_path
    )

    scheduler = build_scheduler(runner, catalog, timezone="UTC")

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "source:scheduled"
    assert jobs[0].kwargs == {"source_id": "scheduled"}
    scheduler.shutdown(wait=False) if scheduler.running else None


def test_background_scheduler_can_request_an_immediate_first_run(tmp_path: Path) -> None:
    catalog = SourceCatalog(
        organizations=(Organization("org", "Organization"),),
        sources=(SourceDefinition("scheduled", "org", "Scheduled", SourceType.API, "fake", schedule="0 0 * * *"),),
    )
    runner = PipelineRunner(SourceRegistry([ScheduledSource()]), catalog, output_directory=tmp_path)
    scheduler = build_scheduler(
        runner, catalog, timezone="UTC", background=True, run_immediately=True
    )
    assert scheduler.get_job("source:scheduled").next_run_time is not None
    scheduler.shutdown(wait=False) if scheduler.running else None
