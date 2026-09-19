"""Convert source-specific values to the canonical Product model."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.models import Availability, Product

CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY"}
CURRENCY_CODES = frozenset({"USD", "GBP", "EUR", "JPY", "KZT", "RUB"})

# Simple scalar measurements are converted to stable base units. Complex values
# such as dimensions remain text so an adapter can preserve their exact meaning.
MEASUREMENT_UNITS: dict[str, tuple[str, Decimal]] = {
    "mg": ("g", Decimal("0.001")),
    "мг": ("g", Decimal("0.001")),
    "g": ("g", Decimal("1")),
    "гр": ("g", Decimal("1")),
    "г": ("g", Decimal("1")),
    "kg": ("g", Decimal("1000")),
    "кг": ("g", Decimal("1000")),
    "oz": ("g", Decimal("28.349523125")),
    "lb": ("g", Decimal("453.59237")),
    "lbs": ("g", Decimal("453.59237")),
    "mm": ("mm", Decimal("1")),
    "мм": ("mm", Decimal("1")),
    "cm": ("mm", Decimal("10")),
    "см": ("mm", Decimal("10")),
    "m": ("mm", Decimal("1000")),
    "метр": ("mm", Decimal("1000")),
    "in": ("mm", Decimal("25.4")),
    "inch": ("mm", Decimal("25.4")),
    "ft": ("mm", Decimal("304.8")),
    "ml": ("ml", Decimal("1")),
    "мл": ("ml", Decimal("1")),
    "l": ("ml", Decimal("1000")),
    "л": ("ml", Decimal("1000")),
    "liter": ("ml", Decimal("1000")),
    "litre": ("ml", Decimal("1000")),
}


def normalize_text(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("required text is missing")
        return None
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    text = " ".join(text.split()).strip()
    if not text:
        if required:
            raise ValueError("required text is empty")
        return None
    return text


def normalize_category(value: Any) -> str | None:
    text = normalize_text(value)
    return text.casefold().title() if text else None


def normalize_price(
    value: Any, currency: str | None = None
) -> tuple[Decimal, str | None]:
    if isinstance(value, bool) or value is None:
        raise ValueError("price is missing")

    if isinstance(value, (Decimal, int, float)):
        try:
            price = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"invalid price: {value!r}") from exc
        if not price.is_finite() or price < 0:
            raise ValueError(f"invalid price: {value!r}")
        return price, _normalize_currency(currency)

    raw = unicodedata.normalize("NFKC", str(value)).strip()
    detected_currency = _normalize_currency(currency) or _detect_currency(raw)
    number = re.sub(r"[^0-9,.-]", "", raw).replace("−", "-")
    if not number or number in {"-", ".", ","}:
        raise ValueError(f"invalid price: {value!r}")

    number = _standardize_decimal_separator(number)
    try:
        price = Decimal(number)
    except InvalidOperation as exc:
        raise ValueError(f"invalid price: {value!r}") from exc
    if not price.is_finite() or price < 0:
        raise ValueError(f"invalid price: {value!r}")
    return price, detected_currency


def _standardize_decimal_separator(value: str) -> str:
    comma = value.rfind(",")
    dot = value.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_separator = "," if comma > dot else "."
        thousands_separator = "." if decimal_separator == "," else ","
        return value.replace(thousands_separator, "").replace(decimal_separator, ".")

    separator = "," if comma >= 0 else "." if dot >= 0 else None
    if separator is None:
        return value
    parts = value.split(separator)
    if len(parts) > 2:
        return "".join(parts)
    if len(parts[-1]) in {1, 2}:
        return value.replace(separator, ".")
    return value.replace(separator, "")


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    normalized = CURRENCY_SYMBOLS.get(normalized, normalized)
    if normalized not in CURRENCY_CODES:
        raise ValueError(f"unsupported currency: {value!r}")
    return normalized


def _detect_currency(value: str) -> str | None:
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in value:
            return code
    upper = value.upper()
    return next((code for code in CURRENCY_CODES if re.search(rf"\b{code}\b", upper)), None)


def normalize_availability(value: Any) -> Availability:
    if isinstance(value, Availability):
        return value
    if isinstance(value, bool):
        return Availability.IN_STOCK if value else Availability.OUT_OF_STOCK
    text = normalize_text(value)
    if text is None:
        return Availability.UNKNOWN
    normalized = text.casefold()
    if any(marker in normalized for marker in ("preorder", "pre-order", "предзаказ")):
        return Availability.PREORDER
    if any(marker in normalized for marker in ("discontinued", "снят с производства")):
        return Availability.DISCONTINUED
    negative = ("out of stock", "unavailable", "sold out", "нет в наличии")
    positive = ("in stock", "low stock", "available", "в наличии")
    if any(marker in normalized for marker in negative):
        return Availability.OUT_OF_STOCK
    if any(marker in normalized for marker in positive):
        return Availability.IN_STOCK
    return Availability.UNKNOWN


def normalize_rating(value: Any) -> float | None:
    if value is None or normalize_text(value) is None:
        return None
    try:
        rating = float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"invalid rating: {value!r}") from exc
    if not 0 <= rating <= 5:
        raise ValueError(f"rating outside 0..5: {value!r}")
    return rating


def normalize_url(value: Any, base_url: str | None = None) -> str:
    raw = normalize_text(value, required=True)
    assert raw is not None
    absolute = urljoin(base_url, raw) if base_url else raw
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid product URL: {value!r}")
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    return urlunsplit((parsed.scheme.lower(), f"{userinfo}{host}{port}", parsed.path or "/", parsed.query, ""))


def normalize_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        result = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid datetime: {value!r}") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def normalize_optional_integer(value: Any, *, field: str) -> int | None:
    if value is None or normalize_text(value) is None:
        return None
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if number < 0:
        raise ValueError(f"invalid {field}: {value!r}")
    return number


def normalize_measurement(value: Any) -> str | None:
    """Normalize one numeric measurement while preserving non-measurement text."""
    text = normalize_text(value)
    if text is None:
        return None
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:[\s\u00a0]\d{3})*|\d+)(?:[.,]\d+)?)\s*([\w]+)",
        text,
        flags=re.UNICODE,
    )
    if match is None:
        return text
    unit = match.group(2).casefold()
    definition = MEASUREMENT_UNITS.get(unit)
    if definition is None:
        return text
    try:
        number = Decimal(match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except InvalidOperation:
        return text
    base_unit, multiplier = definition
    normalized = number * multiplier
    formatted = format(normalized.normalize(), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return f"{formatted} {base_unit}"


def normalize_attributes(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("attributes must be a mapping")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = normalize_text(raw_key)
        item = normalize_measurement(raw_value)
        if key and item:
            result[key] = item
    return result or None


def normalize_product(
    *,
    organization_id: Any,
    source_id: Any,
    external_id: Any,
    name: Any,
    category: Any,
    price: Any,
    currency: str | None,
    availability: Any,
    rating: Any,
    url: Any,
    sku: Any = None,
    brand: Any = None,
    description: Any = None,
    old_price: Any = None,
    quantity: Any = None,
    review_count: Any = None,
    image_url: Any = None,
    attributes: Any = None,
    collected_at: datetime | str | None = None,
    base_url: str | None = None,
) -> Product:
    normalized_price, normalized_currency = normalize_price(price, currency)
    normalized_organization = normalize_text(organization_id, required=True)
    normalized_source = normalize_text(source_id, required=True)
    normalized_id = normalize_text(external_id, required=True)
    normalized_name = normalize_text(name, required=True)
    assert normalized_organization and normalized_source
    assert normalized_id and normalized_name
    normalized_old_price = None
    if old_price is not None and normalize_text(old_price) is not None:
        normalized_old_price, _ = normalize_price(old_price, normalized_currency)
    return Product(
        organization_id=normalized_organization.casefold(),
        source_id=normalized_source.casefold(),
        external_id=normalized_id,
        name=normalized_name,
        category=normalize_category(category),
        price=normalized_price,
        currency=normalized_currency,
        availability=normalize_availability(availability),
        url=normalize_url(url, base_url),
        collected_at=normalize_datetime(collected_at),
        sku=normalize_text(sku),
        brand=normalize_text(brand),
        description=normalize_text(description),
        old_price=normalized_old_price,
        quantity=normalize_optional_integer(quantity, field="quantity"),
        rating=normalize_rating(rating),
        review_count=normalize_optional_integer(review_count, field="review count"),
        image_url=normalize_url(image_url, base_url) if normalize_text(image_url) else None,
        attributes=normalize_attributes(attributes),
    )
