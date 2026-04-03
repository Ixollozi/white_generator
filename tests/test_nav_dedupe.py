from __future__ import annotations

from core.runner import (
    _adjust_nav_for_structure,
    _augment_nav_items,
    _dedupe_nav_items_by_href,
)


def test_dedupe_nav_items_by_href_keeps_first() -> None:
    nav = [
        {"href": "index.php", "label": "Home"},
        {"href": "industries.php", "label": "Industries"},
        {"href": "industries.php", "label": "Industries"},
    ]
    _dedupe_nav_items_by_href(nav)
    assert len(nav) == 2
    assert [x["href"] for x in nav] == ["index.php", "industries.php"]


def test_industries_not_duplicated_after_services_remap() -> None:
    """services.php → industries.php и отдельный пункт Industries из augment давали два одинаковых href."""
    base = [
        {"href": "index.php", "label": "Home"},
        {"href": "about.php", "label": "About"},
        {"href": "services.php", "label": "Services"},
        {"href": "contact.php", "label": "Contact"},
    ]
    page_keys = ["index", "about", "industries", "contact"]
    out = _augment_nav_items(base, page_keys, "php", None)
    _adjust_nav_for_structure(out, page_keys, "php")
    _dedupe_nav_items_by_href(out)
    ind = [x for x in out if x["href"] == "industries.php"]
    assert len(ind) == 1
