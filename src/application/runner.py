"""Run sources independently through the complete processing pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine

from src.database import ProductRepository, create_database_engine, create_schema
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
        if database_url or engine is not None:
            database_engine = engine or create_database_engine(database_url or "")
            create_schema(database_engine)
            self.repository = ProductRepository(database_engine)
            self.repository.sync_catalog(catalog)

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
            LOGGER.exception("Source %s failed: %s", source_id, exc)
            return RunOutcome(
                source_id=source_id,
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                database_run_id=run_id,
                error=str(exc),
            )

    def run_all(self, *, max_pages: int | None = None) -> list[RunOutcome]:
        return [
            self.run(source_id, max_pages=max_pages)
            for source_id in self.registry.ids()
        ]
