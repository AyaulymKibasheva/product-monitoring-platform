"""Configuration model for one independently managed data source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SourceType(StrEnum):
    HTML = "html"
    JAVASCRIPT = "javascript"
    API = "api"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    organization_id: str
    name: str
    source_type: SourceType
    adapter: str
    base_url: str | None = None
    default_currency: str | None = None
    schedule: str | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 3
    backoff_factor: float = 0.5
    active: bool = True
    last_success_at: datetime | None = None
    settings: dict[str, Any] = field(default_factory=dict)

