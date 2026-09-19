"""Organization using or owning monitored product sources."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True, slots=True)
class Organization:
    organization_id: str
    name: str
    active: bool = True
    monitoring_settings: dict[str, Any] = field(default_factory=dict)
