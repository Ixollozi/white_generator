from __future__ import annotations

from core.site_coherence import collect_coherence_issues
from core.site_context import SiteContext
from core.theme_pack import merge_content_overlay


def test_merge_overlay_skips_core_vertical_fields() -> None:
    base = {
        "vertical_id": "hvac",
        "activity_summary": "heating and cooling",
        "seo_blurb": "{brand_name} provides HVAC service.",
        "service_items": [{"title": "Tune-up", "text": "Seasonal maintenance."}],
    }
    overlay = {
        "service_items": [{"title": "Litigation", "text": "Court work."}],
        "seo_blurb": "{brand_name} is a law firm.",
        "activity_summary": "legal counsel",
        "faq_heading": "Questions",
    }
    merged = merge_content_overlay(
        base,
        overlay,
        "AC Pros",
        "heating and cooling",
        brand={"generation_identity": "unit-test"},
    )
    assert merged["service_items"][0]["title"] == "Tune-up"
    assert "law firm" not in (merged.get("seo_blurb") or "")
    assert merged.get("activity_summary") == "heating and cooling"
    assert merged.get("faq_heading") == "Questions"


def test_coherence_flags_legal_vertical_with_hvac_brand() -> None:
    brand = {"brand_name": "ED HVAC", "domain": "edhvac.net"}
    content = {
        "vertical_id": "legal",
        "seo_blurb": "A firm.",
        "service_items": [{"title": "Business law", "text": "x"}],
    }
    issues = collect_coherence_issues(brand, content)
    assert any("legal" in i.lower() and "trades" in i.lower() for i in issues)


def test_render_vars_insights_href_prefers_blog() -> None:
    ctx = SiteContext()
    ctx.meta["page_extension"] = "php"
    ctx.meta["page_keys"] = ["index", "about", "blog", "contact"]
    rv = ctx.render_vars()
    assert rv["insights_href"] == "blog.php"
    assert rv["insights_label"] == "Blog"


def test_render_vars_insights_href_resources_when_no_blog() -> None:
    ctx = SiteContext()
    ctx.meta["page_extension"] = "html"
    ctx.meta["page_keys"] = ["index", "resources", "contact"]
    rv = ctx.render_vars()
    assert rv["insights_href"] == "resources.html"
    assert rv["insights_label"] == "Resources"
