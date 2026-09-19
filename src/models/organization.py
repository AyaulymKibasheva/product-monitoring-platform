"""Organization using or owning monitored product sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Organization:
    organization_id: str
    name: str
    active: bool = True

