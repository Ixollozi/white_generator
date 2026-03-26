from __future__ import annotations

import datetime
import random
import re
import string
from typing import Any


_PREFIXES = (
    "Orbit", "Nova", "Prime", "Vertex", "Sky", "Blue", "North", "Peak",
    "Atlas", "Pulse", "Bright", "Core", "Swift", "True", "Urban",
)
_SUFFIXES = (
    "Reach", "Consult", "Solutions", "Digital", "Media", "Works", "Labs",
    "Group", "Partners", "Studio", "Hub", "Flow", "Edge", "Path",
)

_DOMAIN_SAFE_RE = re.compile(r"[^a-z0-9]+")


def _random_local_part(rng: random.Random) -> str:
    n = rng.randint(4, 8)
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(n))


def _slug_domain(name: str) -> str:
    s = name.strip().lower()
    s = _DOMAIN_SAFE_RE.sub("", s)
    return s[:40] if s else "site"


def _pick_tld(rng: random.Random, tlds: list[str] | None) -> str:
    pool = [x for x in (tlds or []) if isinstance(x, str) and x.strip()]
    if not pool:
        pool = ["com", "net", "org"]
    return rng.choice(pool).lstrip(".").lower()

def _normalize_custom_domain(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"^https?://", "", s)
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0]
    s = s.split("#", 1)[0]
    s = s.strip().strip(".")
    # Allow punycode and dots/hyphens; drop spaces and other junk.
    s = re.sub(r"[^a-z0-9.-]+", "", s)
    # collapse consecutive dots
    s = re.sub(r"\.+", ".", s)
    if not s or "." not in s:
        return ""
    if len(s) > 253:
        s = s[:253]
    return s

def generate_brand(rng: random.Random, brand_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    name = rng.choice(_PREFIXES) + rng.choice(_SUFFIXES)
    year = datetime.date.today().year

    domain_mode = str((brand_cfg or {}).get("domain_mode") or "none")
    tlds_raw = (brand_cfg or {}).get("tlds")
    tlds = [str(x) for x in tlds_raw] if isinstance(tlds_raw, list) else None
    custom_domain = _normalize_custom_domain(str((brand_cfg or {}).get("custom_domain") or ""))

    if domain_mode == "custom" and custom_domain:
        domain = custom_domain
        email = f"contact@{domain}"
    elif domain_mode == "brand_tld":
        domain = f"{_slug_domain(name)}.{_pick_tld(rng, tlds)}"
        email = f"contact@{domain}"
    elif domain_mode == "random_tld":
        domain = f"{_random_local_part(rng)}.{_pick_tld(rng, tlds)}"
        email = f"contact@{domain}"
    else:
        email = f"contact@{_random_local_part(rng)}.{rng.choice(['io', 'co', 'one', 'net'])}"
        domain = email.split("@", 1)[-1]
    phone = f"+1 ({rng.randint(200, 999)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"
    cities = ("Singapore", "Tallinn", "Dublin", "Toronto", "Auckland", "Lisbon")
    address = f"{rng.randint(1, 999)} {rng.choice(['Market', 'Harbour', 'Park', 'River'])} St, {rng.choice(cities)}"
    return {
        "brand_name": name,
        "tagline": f"{name} — clarity, growth, and measurable outcomes.",
        "email": email,
        "phone": phone,
        "address": address,
        "year": year,
        "domain": domain,
        "locale": "en",
    }
