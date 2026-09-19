import csv

from src.utils.validation_writer import write_rejected_csv
from src.validation import RejectedProduct, ValidationIssue


def test_writes_one_row_per_validation_issue(tmp_path) -> None:
    rejected = RejectedProduct(
        index=2,
        organization_id="org",
        source_id="source",
        external_id="bad-1",
        issues=(
            ValidationIssue("required", "name", "name is required"),
            ValidationIssue("invalid_url", "url", "invalid URL"),
        ),
    )
    destination = tmp_path / "rejected.csv"

    write_rejected_csv([rejected], destination)

    with destination.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 2
    assert rows[0]["external_id"] == "bad-1"
    assert rows[1]["error_code"] == "invalid_url"
