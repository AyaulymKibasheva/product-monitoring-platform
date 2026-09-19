"""Load and validate organizations and source definitions from JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import Organization, SourceDefinition, SourceType
from src.normalization import normalize_datetime


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    organizations: tuple[Organization, ...]
    sources: tuple[SourceDefinition, ...]

    def organization(self, organization_id: str) -> Organization:
        for organization in self.organizations:
            if organization.organization_id == organization_id:
                return organization
        raise ValueError(f"unknown organization: {organization_id}")

    def source(self, source_id: str) -> SourceDefinition:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise ValueError(f"unknown source definition: {source_id}")


def load_source_catalog(path: Path) -> SourceCatalog:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"source configuration not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid source configuration JSON: {exc}") from exc

    organizations = tuple(_organization(item) for item in raw.get("organizations", []))
    sources = tuple(_source(item) for item in raw.get("sources", []))
    _validate_catalog(organizations, sources)
    return SourceCatalog(organizations, sources)


def _organization(raw: dict[str, Any]) -> Organization:
    return Organization(
        organization_id=_required(raw, "id"),
        name=_required(raw, "name"),
        active=bool(raw.get("active", True)),
    )


def _source(raw: dict[str, Any]) -> SourceDefinition:
    last_success: datetime | None = None
    if raw.get("last_success_at"):
        last_success = normalize_datetime(raw["last_success_at"])
    try:
        source_type = SourceType(_required(raw, "type"))
    except ValueError as exc:
        raise ValueError(f"unsupported source type: {raw.get('type')!r}") from exc
    return SourceDefinition(
        source_id=_required(raw, "id"),
        organization_id=_required(raw, "organization_id"),
        name=_required(raw, "name"),
        source_type=source_type,
        adapter=_required(raw, "adapter"),
        base_url=raw.get("base_url"),
        default_currency=raw.get("default_currency"),
        schedule=raw.get("schedule"),
        timeout_seconds=float(raw.get("timeout_seconds", 10)),
        max_retries=int(raw.get("max_retries", 3)),
        backoff_factor=float(raw.get("backoff_factor", 0.5)),
        active=bool(raw.get("active", True)),
        last_success_at=last_success,
        settings=dict(raw.get("settings", {})),
    )


def _required(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"configuration field {key!r} is required")
    return value.strip()


def _validate_catalog(
    organizations: tuple[Organization, ...], sources: tuple[SourceDefinition, ...]
) -> None:
    organization_ids = [item.organization_id for item in organizations]
    source_ids = [item.source_id for item in sources]
    if len(organization_ids) != len(set(organization_ids)):
        raise ValueError("duplicate organization ID")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source ID")
    known_organizations = set(organization_ids)
    for source in sources:
        if source.organization_id not in known_organizations:
            raise ValueError(
                f"source {source.source_id!r} references unknown organization "
                f"{source.organization_id!r}"
            )
        if source.timeout_seconds <= 0:
            raise ValueError(f"source {source.source_id!r} timeout must be positive")
        if source.max_retries < 0 or source.backoff_factor < 0:
            raise ValueError(f"source {source.source_id!r} retry settings are invalid")

