"""Source-independent product representation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    DISCONTINUED = "discontinued"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Product:
    organization_id: str
    source_id: str
    external_id: str
    name: str
    category: str | None
    price: Decimal
    currency: str | None
    availability: Availability
    url: str
    collected_at: datetime
    sku: str | None = None
    brand: str | None = None
    description: str | None = None
    old_price: Decimal | None = None
    quantity: int | None = None
    rating: float | None = None
    review_count: int | None = None
    image_url: str | None = None
    attributes: dict[str, str] | None = None

    @property
    def product_id(self) -> str:
        """Backward-compatible alias for the source's external identifier."""
        return self.external_id

    @property
    def source(self) -> str:
        """Backward-compatible alias for source_id."""
        return self.source_id
