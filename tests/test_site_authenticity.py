"""Post-generation checks aligned with _deep_audit heuristics (CI-friendly)."""
from __future__ import annotations

import random
from pathlib import Path

from core.config_loader import resolve_config
from core.runner import generate_all
from integrations.tracking import build_tracking_snippet


def test_default_site_has_no_picsum_and_no_manifest(project_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "auth"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 909, "pages": ["index", "about", "services"]},
        project_root,
    )
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    assert not (root / "build-manifest.json").is_file()
    for p in root.rglob("*.php"):
        text = p.read_text(encoding="utf-8", errors="ignore").lower()
        assert "picsum.photos" not in text


def test_tracking_snippet_varies_with_fingerprint_salt() -> None:
    c = {"analytics_enabled": True}
    a = build_tracking_snippet(c, fingerprint_salt="site-a")
    b = build_tracking_snippet(c, fingerprint_salt="site-b")
    assert a != b
    assert "/collect" in a
    assert "pageview" in a


def test_resolve_image_source_defaults_and_web() -> None:
    from core.image_provider import resolve_image_source

    assert resolve_image_source({}) == "placeholder"
    assert resolve_image_source({"mode": "web"}) == "picsum"


def test_calgary_postal_fsa_matches_street_quadrant() -> None:
    from core.address_catalog import _calgary_fsa_prefixes, _calgary_postal_for_street

    sw = "1701 17 Ave SW"
    postal_sw = _calgary_postal_for_street(sw, 2)
    fsa_sw = postal_sw.replace(" ", "")[:3]
    assert fsa_sw in _calgary_fsa_prefixes(sw)

    nw = "402 4 St NW"
    postal_nw = _calgary_postal_for_street(nw, 0)
    fsa_nw = postal_nw.replace(" ", "")[:3]
    assert fsa_nw in _calgary_fsa_prefixes(nw)
    assert fsa_nw not in _calgary_fsa_prefixes(sw)


def test_vancouver_postal_fsa_is_gva_not_v8_island() -> None:
    from core.address_catalog import _vancouver_fsa_prefixes, _vancouver_postal_for_street

    for street in ("900 W Pender St", "1525 Granville St", "2500 Cambie St"):
        postal = _vancouver_postal_for_street(street, 7)
        fsa = postal.replace(" ", "")[:3]
        assert not fsa.upper().startswith("V8")
        assert fsa in _vancouver_fsa_prefixes(street)


def test_vancouver_district_picks_differ_by_site_identity() -> None:
    from core.address_catalog import pick_districts_for_site

    a = pick_districts_for_site("gen-ident-aaa", "Vancouver", 10, brand_name="Maple Legal Group")
    b = pick_districts_for_site("gen-ident-bbb", "Vancouver", 10, brand_name="Meridian Law LLP")
    sa, sb = set(a), set(b)
    assert sa and sb
    j = len(sa & sb) / len(sa | sb)
    assert j < 1.0


def test_process_steps_accounting_fixed_order() -> None:
    from generators.content_generator import _process_steps_for_vertical

    steps = _process_steps_for_vertical("accounting")
    titles = [str(s.get("title") or "") for s in steps]
    assert titles[0] == "Intake & scoping"
    assert titles[-1] == "Close-out & handoff"
    assert titles.index("Books & documentation") < titles.index("Tax & compliance prep")


def test_accounting_longform_avoids_generic_pm_filler() -> None:
    from generators.content_generator import _longform_section_pack, _pick_sources_for_post

    rr = random.Random(202)
    sources = _pick_sources_for_post(rr, "accounting", "Canada", 4)
    sections = _longform_section_pack(
        rng=rr,
        brand_name="Northline CPA",
        city="Calgary",
        country="Canada",
        activity="bookkeeping and tax",
        vertical_id="accounting",
        title="GST and HST: when registration actually matters",
        category="GST/HST",
        sources=sources,
    )
    joined = " ".join(
        str(ph).lower()
        for sec in sections
        for ph in (sec.get("paragraphs_html") or [])
        if isinstance(sec, dict)
    )
    assert "bottleneck" not in joined
    assert "weekly standups" not in joined
    assert "version-controlled decision logs" not in joined


def test_legal_longform_avoids_dumping_full_title_into_matter_slots() -> None:
    from generators.content_generator import _longform_section_pack, _pick_sources_for_post

    marker = "xyzprivmarker_unused_in_templates_441"
    long_title = (
        "Corporate governance disputes: multi-jurisdictional discovery and privilege logs in accelerated M&A timelines "
        + marker
    )
    rr = random.Random(77)
    sources = _pick_sources_for_post(rr, "legal", "Canada", 4)
    sections = _longform_section_pack(
        rng=rr,
        brand_name="Meridian Law",
        city="Vancouver",
        country="Canada",
        activity="corporate litigation",
        vertical_id="legal",
        title=long_title,
        category="Litigation",
        sources=sources,
    )
    joined = " ".join(
        str(ph)
        for sec in sections
        for ph in (sec.get("paragraphs_html") or [])
        if isinstance(sec, dict)
    )
    assert marker.lower() not in joined.lower()


def test_pricing_tiers_legal_not_saas_names() -> None:
    from generators.content_generator import _pricing_page_and_tiers

    rng = random.Random(3)
    _h, _intro, tiers = _pricing_page_and_tiers("legal", "business law", rng, "Canada")
    names = " | ".join(str(t.get("name") or "") for t in tiers).lower()
    assert "starter" not in names
    assert "standard" not in names
    assert "plus" not in names


def test_merge_content_overlay_backfills_empty_testimonial_quote() -> None:
    from core.theme_pack import merge_content_overlay

    base: dict = {"vertical_id": "legal", "hero_title": "Home"}
    overlay = {
        "testimonial_items": [
            {"quote": "", "name": "J. Smith", "role": "GC"},
        ],
    }
    brand = {"generation_identity": "test-site-1"}
    merged = merge_content_overlay(base, overlay, "Acme LLP", "corporate counsel", brand=brand)
    items = merged.get("testimonial_items")
    assert isinstance(items, list) and items
    assert str(items[0].get("quote") or "").strip()


def test_blog_slug_professional_vertical_dedupes_and_skews_title() -> None:
    from generators.content_generator import _blog_post_slug_parts

    rng = random.Random(9001)
    title = "Corporate tax instalments: avoiding CRA interest surprises"
    s_prof = _blog_post_slug_parts(
        title,
        rng=rng,
        city="Calgary",
        district="Beltline",
        post_type="guide",
        vertical_id="accounting",
    )
    parts = [p for p in s_prof.split("-") if p]
    assert all(parts[i] != parts[i + 1] for i in range(len(parts) - 1))
    # Professional verticals skip district fragments (beltline) to reduce redundant geo tails.
    assert "beltline" not in s_prof.lower()


def test_blog_slug_ignores_site_identity_suffix_collision_handled_elsewhere() -> None:
    """Hash tails on every slug were a generator fingerprint; uniqueness uses _unique_slug_in_set."""
    from generators.content_generator import _blog_post_slug_parts

    rng = random.Random(1)
    title = "GST registration thresholds for growing operators"
    s1 = _blog_post_slug_parts(
        title,
        rng=rng,
        city="Calgary",
        district="Beltline",
        post_type="guide",
        vertical_id="accounting",
        site_identity="identity-aaa",
    )
    rng2 = random.Random(1)
    s2 = _blog_post_slug_parts(
        title,
        rng=rng2,
        city="Calgary",
        district="Beltline",
        post_type="guide",
        vertical_id="accounting",
        site_identity="identity-bbb",
    )
    assert s1 == s2
