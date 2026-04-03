"""Display currency for fictional price strings (schema + UI), keyed off business country."""

from __future__ import annotations


def currency_symbol_for_country(country: str) -> str:
    c = (country or "").strip()
    if c == "Ireland":
        return "€"
    if c == "United Kingdom":
        return "£"
    if c == "Australia":
        return "A$"
    if c == "Singapore":
        return "S$"
    if c == "Canada":
        return "C$"
    return "$"


def localize_money_labels(text: str, country: str) -> str:
    """Replace ASCII $ markers in templates with a country-appropriate symbol."""
    if not text or "$" not in text:
        return text
    sym = currency_symbol_for_country(country)
    if sym == "$":
        return text
    return text.replace("$", sym)
