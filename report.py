"""Create the database snapshot consumed by the Excel report builder."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src.config import Settings
from src.database import create_database_engine
from src.reports import ReportFilters, build_report, write_report_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reporting data from PostgreSQL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--organization")
    parser.add_argument("--source")
    parser.add_argument("--category")
    parser.add_argument("--brand")
    parser.add_argument("--currency")
    parser.add_argument("--from", dest="date_from", type=datetime.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=datetime.fromisoformat)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = Settings.from_env().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is required to build reports")
    filters = ReportFilters(
        organization_id=args.organization,
        source_id=args.source,
        category=args.category,
        brand=args.brand,
        currency=args.currency,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    destination = write_report_json(
        build_report(create_database_engine(database_url), filters), args.output
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
