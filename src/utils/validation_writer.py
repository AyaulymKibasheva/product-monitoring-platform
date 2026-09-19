"""CSV output for records rejected by data-quality checks."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from src.validation import RejectedProduct

REJECTED_FIELDS = (
    "index",
    "organization_id",
    "source_id",
    "external_id",
    "error_code",
    "field",
    "message",
)


def write_rejected_csv(
    rejected: Iterable[RejectedProduct], destination: Path
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REJECTED_FIELDS)
        writer.writeheader()
        for item in rejected:
            for issue in item.issues:
                writer.writerow(
                    {
                        "index": item.index,
                        "organization_id": item.organization_id,
                        "source_id": item.source_id,
                        "external_id": item.external_id,
                        "error_code": issue.code,
                        "field": issue.field,
                        "message": issue.message,
                    }
                )
