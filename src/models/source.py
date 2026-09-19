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
    delay_seconds: float = 0.0
    requests_per_second: float | None = None
    active: bool = True
    last_success_at: datetime | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    monitoring_settings: dict[str, Any] = field(default_factory=dict)

    @property
    def request_delay_seconds(self) -> float:
        rate_delay = 1 / self.requests_per_second if self.requests_per_second else 0.0
        return max(self.delay_seconds, rate_delay)
