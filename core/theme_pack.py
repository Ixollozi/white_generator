from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.content_dates import as_of_year, founded_year_int

from core.person_names import pick_signature_name, site_key_from_brand

_DEFAULT_NAV: list[dict[str, str]] = [
    {"href": "index.php", "label": "Home"},
    {"href": "about.php", "label": "About"},
    {"href": "services.php", "label": "Services"},
    {"href": "contact.php", "label": "Contact"},
]


def default_nav_items() -> list[dict[str, str]]:
    return [dict(x) for x in _DEFAULT_NAV]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _registry_map(project_root: Path) -> dict[str, str]:
    reg = _load_yaml(project_root / "themes" / "registry.yaml")
    raw = reg.get("by_vertical_id") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def theme_folder_for_vertical(project_root: Path, vertical_id: str) -> str | None:
    m = _registry_map(project_root)
    return m.get(str(vertical_id).strip()) or None


def load_theme_pack(project_root: Path, vertical_id: str | None) -> dict[str, Any]:
    """Load themes/<folder>/theme.yaml + content.yaml for a vertical. Missing pack → empty dicts."""
    out: dict[str, Any] = {
        "nav_items": default_nav_items(),
        "index_extras": [],
        "inject_before": "contact_teaser",
        "content_overlay": {},
        "brand_prefixes": None,
        "brand_suffixes": None,
    }
    vid = (vertical_id or "").strip()
    if not vid:
        return out
    folder = theme_folder_for_vertical(project_root, vid)
    if not folder:
        return out
    base = project_root / "themes" / folder
    theme = _load_yaml(base / "theme.yaml")
    content = _load_yaml(base / "content.yaml")

    nav = theme.get("nav_items")
    if isinstance(nav, list) and nav:
        cleaned: list[dict[str, str]] = []
        for item in nav:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            label = str(item.get("label") or "").strip()
            if href and label:
                cleaned.append({"href": href, "label": label})
        if cleaned:
            out["nav_items"] = cleaned

    extras = theme.get("index_extras")
    if isinstance(extras, list):
        out["index_extras"] = [str(x) for x in extras if x]

    inj = theme.get("inject_before")
    if isinstance(inj, str) and inj.strip():
        out["inject_before"] = inj.strip()

    pre = theme.get("brand_prefixes")
    suf = theme.get("brand_suffixes")
    if isinstance(pre, list) and pre:
        out["brand_prefixes"] = [str(x) for x in pre if x]
    if isinstance(suf, list) and suf:
        out["brand_suffixes"] = [str(x) for x in suf if x]

    out["content_overlay"] = content
    return out


def merge_content_overlay(
    base: dict[str, Any],
    overlay: dict[str, Any],
    brand_name: str,
    activity_summary: str,
    brand: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deep-merge theme content fragments using simple {brand_name} / {activity_summary} formatting."""

    cy = as_of_year(brand) if brand else date.today().year
    fy_i = founded_year_int(brand) if brand else None
    founded_s = str(fy_i) if fy_i is not None else str(max(cy - 8, 1998))
    if fy_i is not None:
        msy = max(fy_i, cy - 12)
        if cy > fy_i:
            msy = min(msy, cy - 1)
        member_since_year = str(msy)
        ssy = max(fy_i, cy - 6)
        if cy > fy_i:
            ssy = min(ssy, cy - 1)
        subscriber_since_year = str(ssy)
    else:
        member_since_year = str(cy - 6)
        subscriber_since_year = str(cy - 2)

    fmt_kw: dict[str, str] = {
        "brand_name": brand_name,
        "activity_summary": activity_summary,
        "founded_year": founded_s,
        "current_year": str(cy),
        "member_since_year": member_since_year,
        "subscriber_since_year": subscriber_since_year,
    }

    def fmt_obj(x: Any) -> Any:
        if isinstance(x, str):
            return x.format(**fmt_kw)
        if isinstance(x, dict):
            return {k: fmt_obj(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fmt_obj(v) for v in x]
        return x

    merged = dict(base)
    for k, v in overlay.items():
        merged[k] = fmt_obj(v)

    # Theme packs ship static testimonial attributions; re-key per site so exports don't share the same names.
    if brand:
        items = merged.get("testimonial_items")
        if isinstance(items, list) and items:
            sk = site_key_from_brand(brand)
            vid = str(merged.get("vertical_id") or "").strip() or "generic"
            new_list: list[Any] = []
            for i, row in enumerate(items):
                if isinstance(row, dict):
                    r = dict(row)
                    r["name"] = pick_signature_name(sk, f"theme-pack|{vid}|{i}")
                    q = str(r.get("quote") or "").strip()
                    if not q:
                        r["quote"] = (
                            f"{brand_name} made priorities clear and kept {activity_summary} on track for our team."
                        )
                    new_list.append(r)
                else:
                    new_list.append(row)
            merged["testimonial_items"] = new_list

    return merged
