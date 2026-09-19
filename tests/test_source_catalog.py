import json

import pytest

from src.models import SourceType
from src.sources import build_registry, load_source_catalog


def write_catalog(tmp_path, payload):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_organizations_and_independent_source_settings(tmp_path) -> None:
    path = write_catalog(
        tmp_path,
        {
            "organizations": [
                {"id": "org-a", "name": "Company A"},
                {"id": "org-b", "name": "Company B", "active": False},
            ],
            "sources": [
                {
                    "id": "catalog-a",
                    "organization_id": "org-a",
                    "name": "Catalog A",
                    "type": "html",
                    "adapter": "books_demo",
                    "base_url": "https://example.test/a/",
                    "timeout_seconds": 7,
                    "max_retries": 2,
                    "settings": {"locale": "en"},
                },
                {
                    "id": "catalog-b",
                    "organization_id": "org-b",
                    "name": "Catalog B",
                    "type": "html",
                    "adapter": "books_demo",
                    "base_url": "https://example.test/b/",
                },
            ],
        },
    )

    catalog = load_source_catalog(path)

    assert catalog.organization("org-a").name == "Company A"
    source = catalog.source("catalog-a")
    assert source.source_type is SourceType.HTML
    assert source.timeout_seconds == 7
    assert source.max_retries == 2
    assert source.settings == {"locale": "en"}
    assert build_registry(catalog).ids() == ("catalog-a",)


def test_rejects_source_with_unknown_organization(tmp_path) -> None:
    path = write_catalog(
        tmp_path,
        {
            "organizations": [],
            "sources": [
                {
                    "id": "orphan",
                    "organization_id": "missing",
                    "name": "Orphan",
                    "type": "api",
                    "adapter": "unknown",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="unknown organization"):
        load_source_catalog(path)


def test_rejects_duplicate_source_ids(tmp_path) -> None:
    source = {
        "id": "same",
        "organization_id": "org",
        "name": "Source",
        "type": "html",
        "adapter": "books_demo",
        "base_url": "https://example.test/",
    }
    path = write_catalog(
        tmp_path,
        {
            "organizations": [{"id": "org", "name": "Organization"}],
            "sources": [source, source],
        },
    )

    with pytest.raises(ValueError, match="duplicate source ID"):
        load_source_catalog(path)

