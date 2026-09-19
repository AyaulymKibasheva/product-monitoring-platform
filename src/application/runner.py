"""Run sources independently through the complete processing pipeline."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine

from src.database import ProductRepository, create_database_engine, create_schema
from src.notifications import NotificationDispatcher
from src.sources import SourceCatalog, SourceRegistry
from src.utils.csv_writer import write_products_csv
from src.utils.validation_writer import write_rejected_csv
from src.validation import ProductValidator

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    source_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    found: int = 0
    accepted: int = 0
    rejected: int = 0
    source_errors: int = 0
    duplicate_count: int = 0
    database_run_id: int | None = None
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class PipelineRunner:
    def __init__(
        self,
        registry: SourceRegistry,
        catalog: SourceCatalog,
        *,
        output_directory: Path = Path("data"),
        database_url: str | None = None,
        engine: Engine | None = None,
    ) -> None:
        self.registry = registry
        self.catalog = catalog
        self.output_directory = output_directory
        self.validator = ProductValidator()
        self.repository: ProductRepository | None = None
        self.notifications: NotificationDispatcher | None = None
        if database_url or engine is not None:
            database_engine = engine or create_database_engine(database_url or "")
            create_schema(database_engine)
            self.repository = ProductRepository(database_engine)
            self.repository.sync_catalog(catalog)
            self.notifications = NotificationDispatcher(database_engine)

    def run(
        self,
        source_id: str,
        *,
        max_pages: int | None = None,
        output: Path | None = None,
        rejected_output: Path | None = None,
    ) -> RunOutcome:
        started_at = datetime.now(timezone.utc)
        try:
            source_result = self.registry.get(source_id).collect(max_pages=max_pages)
            validation = self.validator.validate_batch(source_result.products)
            destination = output or self.output_directory / f"{source_id}.csv"
            rejected_destination = rejected_output or destination.with_name(
                f"{destination.stem}.rejected.csv"
            )
            write_products_csv(validation.valid_products, destination)
            write_rejected_csv(validation.rejected_products, rejected_destination)
            run_id = None
            if self.repository:
                run_id = self.repository.save_run(
                    source_result, validation, started_at=started_at
                )
                self._notify(run_id)
            finished_at = datetime.now(timezone.utc)
            status = "partial" if source_result.stats.errors else "success"
            outcome = RunOutcome(
                source_id=source_id,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                found=source_result.stats.records_found,
                accepted=validation.accepted_count,
                rejected=validation.rejected_count,
                source_errors=len(source_result.stats.errors),
                duplicate_count=validation.duplicate_count,
                database_run_id=run_id,
            )
            LOGGER.info(
                "Source %s %s in %.3fs: found=%d accepted=%d rejected=%d "
                "duplicates=%d source_errors=%d database_run_id=%s",
                source_id,
                status,
                outcome.duration_seconds,
                outcome.found,
                outcome.accepted,
                outcome.rejected,
                outcome.duplicate_count,
                outcome.source_errors,
                run_id,
            )
            return outcome
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            run_id = None
            if self.repository:
                run_id = self.repository.save_failed_run(
                    source_id, started_at=started_at, error=exc
                )
                self._notify(run_id)
            LOGGER.exception("Source %s failed: %s", source_id, exc)
            return RunOutcome(
                source_id=source_id,
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                database_run_id=run_id,
                error=str(exc),
            )

    def run_all(
        self, *, max_pages: int | None = None, max_workers: int = 4
    ) -> list[RunOutcome]:
        source_ids = self.registry.ids()
        if len(source_ids) < 2 or self._uses_memory_sqlite():
            return [self.run(source_id, max_pages=max_pages) for source_id in source_ids]
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(source_ids)),
            thread_name_prefix="source",
        ) as executor:
            futures = {
                source_id: executor.submit(self.run, source_id, max_pages=max_pages)
                for source_id in source_ids
            }
            return [futures[source_id].result() for source_id in source_ids]

    def _uses_memory_sqlite(self) -> bool:
        return bool(
            self.repository
            and self.repository.engine.dialect.name == "sqlite"
            and self.repository.engine.url.database in {None, "", ":memory:"}
        )

    def dispatch_notifications(self) -> int:
        return self.notifications.dispatch_pending() if self.notifications else 0

    def _notify(self, run_id: int) -> None:
        if not self.notifications:
            return
        try:
            self.notifications.process_run(run_id)
        except Exception:
            LOGGER.exception("Notification processing failed for run %s", run_id)
