"""Runtime checks: brand/domain vs vertical_id vs core content (prevents HVAC + law-firm copy)."""

from __future__ import annotations

import re
from typing import Any

# Brand/domain hints for field-service / trades (not exhaustive).
_TRADE_MARKERS: tuple[str, ...] = (
    "hvac",
    "heating",
    "cooling",
    "air conditioning",
    "plumb",
    "electric",
    "roof",
    "landscap",
    "pest",
    "moving",
    "auto repair",
    "automotive",
    "mechanic",
    "furnace",
    "boiler",
    "ductless",
    "mini-split",
    "rtu",
    "climate",
)

# Strong legal positioning in brand string when vertical is not legal.
_LEGAL_BRAND_MARKERS: tuple[str, ...] = (
    "law firm",
    "llp",
    "llc law",
    "attorneys",
    "solicitors",
    "barrister",
    "legal group",
    "counsel at law",
)

# Service titles that should only appear under legal (substring match, case-insensitive).
_LEGAL_SERVICE_TITLE_FRAGMENTS: tuple[str, ...] = (
    "business law",
    "litigation",
    "contract drafting",
    "dispute resolution",
    "regulatory compliance",
    "estate planning law",
    "employment law",
)


def _haystack(brand: dict[str, Any], content: dict[str, Any]) -> str:
    parts = [
        str(brand.get("brand_name") or ""),
        str(brand.get("domain") or ""),
        str(brand.get("email") or ""),
    ]
    return " ".join(parts).lower()


def _seo_text(content: dict[str, Any]) -> str:
    return " ".join(
        [
            str(content.get("seo_blurb") or ""),
            str(content.get("about_body") or "")[:400],
        ]
    ).lower()


def collect_coherence_issues(brand: dict[str, Any], content: dict[str, Any]) -> list[str]:
    """Return human-readable issue strings; empty if nothing suspicious."""
    issues: list[str] = []
    vid = str(content.get("vertical_id") or "").strip()
    hay = _haystack(brand, content)
    seo = _seo_text(content)

    if vid == "legal":
        if any(m in hay for m in _TRADE_MARKERS):
            issues.append(
                f"vertical_id is legal but brand/domain suggests trades/HVAC/plumbing/etc.: {brand.get('brand_name')!r}"
            )
    else:
        if any(m in hay for m in _LEGAL_BRAND_MARKERS):
            issues.append(
                f"vertical_id is {vid!r} but brand/domain suggests a law practice: {brand.get('brand_name')!r}"
            )
        if "law firm" in seo and vid not in ("legal", "news"):
            issues.append(f"seo_blurb mentions law firm but vertical_id is {vid!r}")

    if vid and vid != "legal":
        svc = content.get("service_items")
        if isinstance(svc, list):
            for it in svc:
                if not isinstance(it, dict):
                    continue
                t = str(it.get("title") or "").lower()
                for frag in _LEGAL_SERVICE_TITLE_FRAGMENTS:
                    if frag in t:
                        issues.append(
                            f"service title {it.get('title')!r} looks legal-specific but vertical_id is {vid!r}"
                        )
                        break

    return issues


def validate_site_coherence(
    brand: dict[str, Any],
    content: dict[str, Any],
    *,
    strict: bool = False,
) -> None:
    issues = collect_coherence_issues(brand, content)
    if not issues:
        return
    msg = "Site coherence warnings:\n  - " + "\n  - ".join(issues)
    if strict:
        raise ValueError(msg)
    # Non-strict: log once via print would be wrong for library; use logging if configured.
    import logging

    logging.getLogger("white_generator.coherence").warning(msg)
