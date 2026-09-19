"""Source-independent command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.application import PipelineRunner
from src.application.scheduler import build_scheduler
from src.config import Settings
from src.sources import build_registry, load_source_catalog
from src.utils.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect products from a configured source")
    parser.add_argument("--source", help="Registered source ID")
    parser.add_argument("--all-sources", action="store_true", help="Run every active source once")
    parser.add_argument("--scheduler", action="store_true", help="Run the configured scheduler")
    parser.add_argument("--list-sources", action="store_true", help="List source IDs and exit")
    parser.add_argument("--output", type=Path, help="CSV destination")
    parser.add_argument("--rejected-output", type=Path, help="Rejected-record CSV destination")
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Maximum pages to fetch; 0 means no limit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    catalog = load_source_catalog(settings.source_config_path)
    registry = build_registry(catalog)
    runner = PipelineRunner(
        registry,
        catalog,
        output_directory=settings.output_path.parent,
        database_url=settings.database_url,
    )

    if args.list_sources:
        print("\n".join(registry.ids()))
        return 0

    max_pages = settings.max_pages if args.max_pages is None else args.max_pages
    if max_pages < 0:
        raise SystemExit("--max-pages must be zero or greater")

    if args.scheduler:
        scheduler = build_scheduler(
            runner, catalog, timezone=settings.scheduler_timezone
        )
        scheduler.start()
        return 0
    if args.all_sources:
        outcomes = runner.run_all(max_pages=max_pages or None)
        return 1 if any(item.status == "failed" for item in outcomes) else 0

    outcome = runner.run(
        args.source or settings.default_source_id,
        max_pages=max_pages or None,
        output=args.output or settings.output_path,
        rejected_output=args.rejected_output,
    )
    return 1 if outcome.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
