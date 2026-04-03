"""Derive schema.org price fields and a unified priceRange string from service_items.price_from."""

from __future__ import annotations

import re
from typing import Any


def currency_iso_for_country(country: str) -> str:
    c = (country or "").strip()
    if c == "Ireland":
        return "EUR"
    if c == "United Kingdom":
        return "GBP"
    if c == "Australia":
        return "AUD"
    if c == "Singapore":
        return "SGD"
    if c == "Canada":
        return "CAD"
    return "USD"


def _strip_noise(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _to_float(num: str, suffix: str | None) -> float | None:
    try:
        n = float(num.replace(",", ""))
    except ValueError:
        return None
    if suffix and suffix.lower() == "k":
        n *= 1000.0
    elif suffix and suffix.lower() == "m":
        n *= 1_000_000.0
    return n


# Currency marker + amount + optional k/m suffix (case-insensitive).
_RE_MONEY = re.compile(r"(?i)(?:[\$€£]|S\$|A\$|C\$|CA\$)\s*([\d,]+(?:\.\d+)?)\s*([km])?\b")


def extract_amounts_from_price_label(label: str) -> list[float]:
    """Return numeric amounts found in a single price_from line (for min/max)."""
    s = _strip_noise(label)
    if not s:
        return []
    out: list[float] = []
    for m in _RE_MONEY.finditer(s):
        v = _to_float(m.group(1), m.group(2))
        if v is not None and v > 0:
            out.append(v)
    return out


def first_schema_price_string(label: str) -> tuple[str | None, float | None]:
    """First monetary amount as schema Offer price string."""
    amounts = extract_amounts_from_price_label(label)
    if not amounts:
        return None, None
    v = amounts[0]
    if v >= 1000 and abs(v - round(v)) < 0.02:
        ps = f"{int(round(v))}"
    elif v >= 100:
        ps = f"{int(round(v))}"
    else:
        ps = f"{v:.2f}".rstrip("0").rstrip(".")
    return ps, v


def derive_price_range_and_enrich_offers(
    service_items: list[Any],
    *,
    country: str,
    vertical_id: str,
) -> tuple[str, str]:
    """
    Set per-item schema_price / schema_price_currency when parseable.
    Returns (priceRange_display_string, iso_currency).
    """
    ccy = currency_iso_for_country(country)
    vid = (vertical_id or "").strip()
    if vid == "news":
        return "", ccy
    all_amounts: list[float] = []
    for it in service_items:
        if not isinstance(it, dict):
            continue
        raw = str(it.get("price_from") or "").strip()
        if not raw:
            it.pop("schema_price", None)
            it.pop("schema_price_currency", None)
            continue
        ps, _fv = first_schema_price_string(raw)
        if ps:
            it["schema_price"] = ps
            it["schema_price_currency"] = ccy
            all_amounts.extend(extract_amounts_from_price_label(raw))
        else:
            it.pop("schema_price", None)
            it.pop("schema_price_currency", None)

    if not all_amounts:
        return "", ccy
    lo, hi = min(all_amounts), max(all_amounts)
    sym = "$"
    if ccy == "EUR":
        sym = "€"
    elif ccy == "GBP":
        sym = "£"
    elif ccy == "AUD":
        sym = "A$"
    elif ccy == "SGD":
        sym = "S$"
    elif ccy == "CAD":
        sym = "C$"

    def _fmt(n: float) -> str:
        if n >= 1000:
            return f"{sym}{int(round(n)):,}"
        if abs(n - round(n)) < 0.02:
            return f"{sym}{int(round(n))}"
        return f"{sym}{n:.2f}".rstrip("0").rstrip(".")

    if abs(hi - lo) < 0.01:
        if vid == "cafe_restaurant":
            pr = f"Dishes from {_fmt(lo)}"
        else:
            pr = f"Typical entry points around {_fmt(lo)}"
    else:
        if vid == "cafe_restaurant":
            pr = f"Dishes from {_fmt(lo)} to {_fmt(hi)}"
        else:
            pr = f"Services from {_fmt(lo)} to {_fmt(hi)}"
    return pr, ccy
