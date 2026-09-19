"""Validation rules applied after normalization and before persistence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from src.models import Availability, Product


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class RejectedProduct:
    index: int
    organization_id: str
    source_id: str
    external_id: str
    issues: tuple[ValidationIssue, ...]


@dataclass(slots=True)
class ProductValidationResult:
    valid_products: list[Product] = field(default_factory=list)
    rejected_products: list[RejectedProduct] = field(default_factory=list)
    total_received: int = 0
    duplicate_count: int = 0

    @property
    def accepted_count(self) -> int:
        return len(self.valid_products)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_products)


class ProductValidator:
    """Validate a normalized batch without stopping at the first bad record."""

    def validate_batch(self, products: list[Product]) -> ProductValidationResult:
        result = ProductValidationResult(total_received=len(products))
        seen: set[tuple[str, str, str]] = set()

        for index, product in enumerate(products):
            issues = self.validate(product)
            key = self._identity(product)
            if key in seen:
                issues.append(
                    ValidationIssue(
                        "duplicate",
                        "external_id",
                        "duplicate product identity within this source run",
                    )
                )
                result.duplicate_count += 1
            else:
                seen.add(key)

            if issues:
                result.rejected_products.append(
                    RejectedProduct(
                        index=index,
                        organization_id=self._safe_text(product.organization_id),
                        source_id=self._safe_text(product.source_id),
                        external_id=self._safe_text(product.external_id),
                        issues=tuple(issues),
                    )
                )
            else:
                result.valid_products.append(product)

        return result

    def validate(self, product: Product) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        self._required_text(issues, "organization_id", product.organization_id)
        self._required_text(issues, "source_id", product.source_id)
        self._required_text(issues, "external_id", product.external_id)
        self._required_text(issues, "name", product.name)

        if not isinstance(product.price, Decimal):
            self._add(issues, "invalid_type", "price", "price must be Decimal")
        elif not product.price.is_finite() or product.price < 0:
            self._add(issues, "invalid_value", "price", "price must be finite and non-negative")

        if not isinstance(product.currency, str) or not re.fullmatch(
            r"[A-Z]{3}", product.currency
        ):
            self._add(issues, "invalid_currency", "currency", "currency must be a 3-letter ISO code")

        if not isinstance(product.availability, Availability):
            self._add(
                issues,
                "invalid_availability",
                "availability",
                "availability must use a canonical status",
            )

        self._validate_url(issues, "url", product.url, required=True)
        if product.image_url is not None:
            self._validate_url(issues, "image_url", product.image_url, required=False)

        if product.rating is not None and (
            isinstance(product.rating, bool)
            or not isinstance(product.rating, (int, float))
            or not math.isfinite(product.rating)
            or not 0 <= product.rating <= 5
        ):
            self._add(issues, "invalid_rating", "rating", "rating must be between 0 and 5")

        for field_name, value in (
            ("quantity", product.quantity),
            ("review_count", product.review_count),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                self._add(
                    issues,
                    "invalid_value",
                    field_name,
                    f"{field_name} must be a non-negative integer",
                )

        if not isinstance(product.collected_at, datetime) or product.collected_at.tzinfo is None:
            self._add(
                issues,
                "invalid_datetime",
                "collected_at",
                "collected_at must be timezone-aware",
            )

        if product.attributes is not None and (
            not isinstance(product.attributes, dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in product.attributes.items()
            )
        ):
            self._add(
                issues,
                "invalid_type",
                "attributes",
                "attributes must contain string keys and values",
            )
        return issues

    @staticmethod
    def _identity(product: Product) -> tuple[str, str, str]:
        return (
            ProductValidator._safe_text(product.organization_id).casefold(),
            ProductValidator._safe_text(product.source_id).casefold(),
            ProductValidator._safe_text(product.external_id).casefold(),
        )

    @staticmethod
    def _safe_text(value: object) -> str:
        return value if isinstance(value, str) else str(value or "")

    @staticmethod
    def _add(
        issues: list[ValidationIssue], code: str, field: str, message: str
    ) -> None:
        issues.append(ValidationIssue(code, field, message))

    def _required_text(
        self, issues: list[ValidationIssue], field_name: str, value: object
    ) -> None:
        if not isinstance(value, str):
            self._add(issues, "invalid_type", field_name, f"{field_name} must be text")
        elif not value.strip():
            self._add(issues, "required", field_name, f"{field_name} is required")

    def _validate_url(
        self,
        issues: list[ValidationIssue],
        field_name: str,
        value: object,
        *,
        required: bool,
    ) -> None:
        if not isinstance(value, str) or not value.strip():
            if required:
                self._add(issues, "required", field_name, f"{field_name} is required")
            else:
                self._add(issues, "invalid_url", field_name, f"{field_name} must be an HTTP URL")
            return
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._add(issues, "invalid_url", field_name, f"{field_name} must be an HTTP URL")

