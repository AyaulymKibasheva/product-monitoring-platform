"""Canonical product validation and data-quality reporting."""

from .product import (
    ProductValidationResult,
    ProductValidator,
    RejectedProduct,
    ValidationIssue,
)

__all__ = [
    "ProductValidationResult",
    "ProductValidator",
    "RejectedProduct",
    "ValidationIssue",
]
