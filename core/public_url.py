from __future__ import annotations

from typing import Any

_PLACEHOLDER_BASES = frozenset(
    {
        "",
        "https://example.com",
        "http://example.com",
        "https://www.example.com",
        "http://www.example.com",
    }
)


def effective_public_base_url(requested: str | None, brand: dict[str, Any]) -> str:
    """
    Use configured base_url when user set a real domain. If still the generic placeholder (or empty),
    derive https://{brand.domain} so canonical, sitemap, and OG stay consistent with contact email.
    """
    r = (requested or "").strip().rstrip("/")
    if r in _PLACEHOLDER_BASES:
        dom = brand.get("domain")
        if isinstance(dom, str):
            d = dom.strip().lower().strip(".")
            if d and "." in d and "example.com" not in d:
                return f"https://{d}"
    if not r:
        dom = brand.get("domain")
        if isinstance(dom, str) and "." in dom.strip():
            d = dom.strip().lower().strip(".")
            return f"https://{d}"
        return "https://example.com"
    return r
