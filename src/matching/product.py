"""Conservative product matching for deduplication across sources."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from src.models import Product

GLOBAL_ID_KEYS = frozenset({"gtin", "ean", "ean13", "upc", "isbn", "isbn13"})


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    product_id: int
    organization_id: str
    name: str
    sku: str | None
    brand: str | None
    url: str
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MatchDecision:
    candidate_product_id: int | None
    score: float
    reason: str
    auto_merge: bool


class ProductMatcher:
    def __init__(self, auto_merge_threshold: float = 0.95) -> None:
        self.auto_merge_threshold = auto_merge_threshold

    def best_match(
        self, incoming: Product, candidates: list[MatchCandidate]
    ) -> MatchDecision:
        decisions = [self.compare(incoming, candidate) for candidate in candidates]
        if not decisions:
            return MatchDecision(None, 0.0, "no_candidates", False)
        return max(decisions, key=lambda item: item.score)

    def compare(self, incoming: Product, candidate: MatchCandidate) -> MatchDecision:
        if incoming.organization_id != candidate.organization_id:
            return MatchDecision(candidate.product_id, 0.0, "different_organization", False)

        incoming_ids = self._global_ids(incoming.attributes)
        candidate_ids = self._global_ids(candidate.attributes)
        if incoming_ids and candidate_ids and incoming_ids.intersection(candidate_ids):
            return self._decision(candidate.product_id, 1.0, "global_identifier")

        incoming_sku = self._key(incoming.sku)
        candidate_sku = self._key(candidate.sku)
        incoming_brand = self._key(incoming.brand)
        candidate_brand = self._key(candidate.brand)
        if incoming_sku and candidate_sku:
            if incoming_sku == candidate_sku:
                if incoming_brand and candidate_brand and incoming_brand != candidate_brand:
                    return MatchDecision(candidate.product_id, 0.0, "brand_conflict", False)
                return self._decision(candidate.product_id, 0.98, "sku")
            # Explicitly different SKUs normally represent distinct variants.
            return MatchDecision(candidate.product_id, 0.0, "different_sku", False)

        if self._key(incoming.url) == self._key(candidate.url):
            return self._decision(candidate.product_id, 0.97, "canonical_url")

        same_name = self._key(incoming.name) == self._key(candidate.name)
        same_brand = incoming_brand and incoming_brand == candidate_brand
        if same_name and same_brand:
            return self._decision(candidate.product_id, 0.90, "name_and_brand")
        if same_name:
            return self._decision(candidate.product_id, 0.60, "name_only")
        return MatchDecision(candidate.product_id, 0.0, "no_match", False)

    def _decision(self, product_id: int, score: float, reason: str) -> MatchDecision:
        return MatchDecision(
            product_id,
            score,
            reason,
            score >= self.auto_merge_threshold,
        )

    @staticmethod
    def _key(value: object) -> str:
        if value is None:
            return ""
        normalized = unicodedata.normalize("NFKC", str(value)).casefold()
        return re.sub(r"[^a-z0-9а-яё]+", "", normalized)

    @classmethod
    def _global_ids(cls, attributes: dict[str, Any] | None) -> set[str]:
        if not attributes:
            return set()
        return {
            cls._key(value)
            for key, value in attributes.items()
            if cls._key(key) in GLOBAL_ID_KEYS and cls._key(value)
        }

