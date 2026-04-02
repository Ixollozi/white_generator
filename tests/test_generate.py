from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config_loader import resolve_config
from core.runner import generate_all

# Explicit page set so tests stay deterministic while the template allows optional pages.
_CORP_FULL_PAGES = [
    "index",
    "about",
    "contact",
    "services",
    "blog",
    "faq",
]


def test_generate_creates_core_files(project_root: Path, tmp_path: Path):
    out = tmp_path / "generated"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 7, "pages": _CORP_FULL_PAGES},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    assert len(sites) == 1
    root = sites[0]
    assert (root / "index.php").is_file()
    assert (root / "about.php").is_file()
    assert (root / "contact.php").is_file()
    assert (root / "services.php").is_file()
    assert (root / "blog.php").is_file()
    assert (root / "faq.php").is_file()
    assert (root / "sitemap.xml").is_file()
    assert (root / "robots.txt").is_file()
    assert (root / ".htaccess").is_file()
    text = (root / "index.php").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "<main" in text
    assert 'rel="canonical"' in text
    assert "application/ld+json" in text


def test_default_skips_build_manifest(project_root: Path, tmp_path: Path):
    out = tmp_path / "no_manifest"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 701, "pages": ["index"]},
        project_root,
    )
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    assert not (root / "build-manifest.json").is_file()
    ui = root / ".ui-site-meta.json"
    assert ui.is_file()
    meta = json.loads(ui.read_text(encoding="utf-8"))
    assert meta.get("template_id") == "corporate_v1"
    assert meta.get("vertical_id")


def test_write_build_manifest_creates_json(project_root: Path, tmp_path: Path):
    out = tmp_path / "with_manifest"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 702,
            "pages": ["index"],
            "write_build_manifest": True,
        },
        project_root,
    )
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    assert (root / "build-manifest.json").is_file()
    assert not (root / ".ui-site-meta.json").is_file()
    data = json.loads((root / "build-manifest.json").read_text(encoding="utf-8"))
    assert data.get("template_id") == "corporate_v1"


def test_manifest_lists_components(project_root: Path, tmp_path: Path):
    out = tmp_path / "o2"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["reference_v1"], "seed": 1, "write_build_manifest": True},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    import json

    data = json.loads((sites[0] / "build-manifest.json").read_text(encoding="utf-8"))
    assert data["template_id"] == "reference_v1"
    assert "pages" in data
    assert "index" in data["pages"]


def test_generate_uses_custom_site_name(project_root: Path, tmp_path: Path):
    out = tmp_path / "named"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 11, "site_name": "my-brand"},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    assert len(sites) == 1
    assert sites[0].name == "my-brand"
    assert (sites[0] / "index.php").is_file()


def test_brand_includes_year_and_domain(project_root: Path, tmp_path: Path):
    out = tmp_path / "o3"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 3,
            "brand": {"domain_mode": "brand_tld", "tlds": ["com"]},
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    text = (sites[0] / "index.php").read_text(encoding="utf-8")
    # Generation must complete; manifest is optional by default.
    # Domain should be a .com and used in email (rendered on contact/footer depending on template).
    assert ".com" in text


def test_brand_uses_custom_domain_mode(project_root: Path, tmp_path: Path):
    out = tmp_path / "o4"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 5,
            "brand": {"domain_mode": "custom", "custom_domain": "my-example.test"},
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    text = (sites[0] / "index.php").read_text(encoding="utf-8")
    assert "my-example.test" in text


def test_images_upload_mode_copies_asset_pack(project_root: Path, tmp_path: Path):
    # Arrange: create a fake asset pack with one "image" file
    pack_id = "testpack"
    assets_dir = project_root / "assets"
    src = assets_dir / "asset_packs" / pack_id / "originals"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    out = tmp_path / "o5"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 9,
            "images": {"mode": "upload", "asset_pack_id": pack_id},
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    assert (sites[0] / "img" / "upload" / "a.png").is_file()
    html = (sites[0] / "index.php").read_text(encoding="utf-8")
    assert 'src="img/upload/a.png"' in html


def test_generate_with_vertical_cleaning(project_root: Path, tmp_path: Path):
    out = tmp_path / "vertical_cleaning"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 42,
            "vertical": "cleaning",
            "write_build_manifest": True,
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    manifest = json.loads((sites[0] / "build-manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("vertical_id") == "cleaning"
    html = (sites[0] / "index.php").read_text(encoding="utf-8")
    assert "cleaning" in html.lower()


def test_theme_pack_injects_blocks_on_index(project_root: Path, tmp_path: Path):
    out = tmp_path / "theme_blocks"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 100,
            "vertical": "cleaning",
            "write_build_manifest": True,
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    manifest = json.loads((sites[0] / "build-manifest.json").read_text(encoding="utf-8"))
    types = [x["type"] for x in manifest["pages"]["index"]]
    assert "testimonials" in types
    assert "faq" in types
    assert "gallery_section" in types


def test_sitemap_has_lastmod_and_trust_pages(project_root: Path, tmp_path: Path):
    out = tmp_path / "sitemap_trust"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 21, "pages": _CORP_FULL_PAGES},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    root = sites[0]
    sm = (root / "sitemap.xml").read_text(encoding="utf-8")
    assert "<lastmod>" in sm
    assert (root / "refund-policy.php").is_file()
    assert (root / "shipping-policy.php").is_file()
    assert "refund-policy.php" in sm


def test_production_legal_mode_has_no_placeholder_language(project_root: Path, tmp_path: Path):
    out = tmp_path / "prod_legal"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 77,
            "legal": {"mode": "production"},
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    root = sites[0]
    # Check a couple of policy pages explicitly
    for fname in ("privacy-policy.php", "terms-of-service.php", "cookie-policy.php"):
        txt = (root / fname).read_text(encoding="utf-8", errors="ignore").lower()
        assert "this text is generated" not in txt
        assert "placeholder" not in txt
        assert "counsel-approved" not in txt


def test_noise_randomize_ids_keeps_cookie_banner_hooks(project_root: Path, tmp_path: Path):
    out = tmp_path / "noise_cookie"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 78,
            "noise": {"randomize_ids": True, "randomize_classes": True},
        },
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    html = (sites[0] / "index.php").read_text(encoding="utf-8", errors="ignore")
    assert 'id="cookie-consent"' in html
    assert 'id="cookie-ok"' in html


def test_no_mojibake_in_news_vertical(project_root: Path, tmp_path: Path):
    out = tmp_path / "news_no_mojibake"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 303, "vertical": "news"},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    root = sites[0]
    bad = ["вЂ", "â€™", "â€”", "�"]
    for p in root.glob("*.php"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        assert not any(b in p.name for b in bad)
        assert not any(b in txt for b in bad)


def test_news_vertical_policy_set_excludes_refund_shipping(project_root: Path, tmp_path: Path):
    out = tmp_path / "news_policy_set"
    cfg = resolve_config(None, {"count": 1, "templates": ["corporate_v1"], "seed": 304, "vertical": "news"}, project_root)
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    assert not (root / "refund-policy.php").is_file()
    assert not (root / "shipping-policy.php").is_file()
    assert (root / "corrections-policy.php").is_file()
    assert (root / "ethics-policy.php").is_file()
    assert (root / "republishing-policy.php").is_file()


def test_zip_has_non_identical_mtimes(project_root: Path, tmp_path: Path):
    out = tmp_path / "zip_mtime"
    cfg = resolve_config(None, {"count": 1, "templates": ["corporate_v1"], "seed": 305, "zip_each_site": True}, project_root)
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    zpath = root.with_suffix(".zip")
    assert zpath.is_file()
    import zipfile

    with zipfile.ZipFile(zpath, "r") as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
    assert len(infos) > 5
    mtimes = {i.date_time for i in infos}
    assert len(mtimes) > 1
    arc_names = {i.filename.replace("\\", "/") for i in infos}
    assert ".ui-site-meta.json" not in arc_names
    assert "build-manifest.json" not in arc_names


def test_news_vertical_generates_longform_and_staff_page(project_root: Path, tmp_path: Path):
    out = tmp_path / "news_site"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "seed": 202, "vertical": "news"},
        project_root,
    )
    cfg["output_path"] = out
    sites = generate_all(cfg)
    root = sites[0]
    assert (root / "authors.php").is_file()
    arts = list(root.glob("article-*.php"))
    assert len(arts) >= 15
    one = next(p for p in arts if p.name.endswith(".php"))
    html = one.read_text(encoding="utf-8")
    assert "NewsArticle" in html or "application/ld+json" in html
    assert "Sources" in html
    assert "Reader comments" in html
    sm = (root / "sitemap.xml").read_text(encoding="utf-8")
    assert "authors.php" in sm
    assert one.name in sm


def test_clothing_catalog_is_single_shop_page(project_root: Path, tmp_path: Path):
    out = tmp_path / "clothing_shop"
    cfg = resolve_config(
        None,
        {
            "count": 1,
            "templates": ["corporate_v1"],
            "seed": 9001,
            "vertical": "clothing",
            "pages": ["index", "shop", "cart", "checkout"],
        },
        project_root,
    )
    cfg["output_path"] = out
    root = generate_all(cfg)[0]
    assert not list(root.glob("product-*")), "catalog should not emit per-product files"
    shop = (root / "shop.php").read_text(encoding="utf-8")
    assert 'id="p-' in shop
    assert "#p-" in shop
    sm = (root / "sitemap.xml").read_text(encoding="utf-8")
    assert "shop.php" in sm
    assert "product-" not in sm


def test_unknown_vertical_raises(project_root: Path, tmp_path: Path):
    out = tmp_path / "bad_vertical"
    cfg = resolve_config(
        None,
        {"count": 1, "templates": ["corporate_v1"], "vertical": "___not_a_real_vertical___"},
        project_root,
    )
    cfg["output_path"] = out
    with pytest.raises(ValueError, match="Unknown vertical"):
        generate_all(cfg)


def test_slugify_respects_word_boundaries() -> None:
    from generators.content_generator import _slugify_ascii

    s = _slugify_ascii(
        "readiness-for-steps-review-work-without-slowing-ship-sandymount-audit",
        max_len=52,
    )
    assert not s.endswith("shi")
    assert len(s) <= 52


def test_person_names_vary_by_site_identity() -> None:
    from core.person_names import pick_full_name

    a = pick_full_name("site-a|vancouver", "consulting|delivery")
    b = pick_full_name("site-b|vancouver", "consulting|delivery")
    assert a != b
    assert " " in a and " " in b


def test_localize_money_labels_ireland() -> None:
    from core.money_locale import localize_money_labels

    out = localize_money_labels("$500–$3,000", "Ireland")
    assert "€" in out
    assert "$" not in out


def test_blog_slug_parts_avoid_legacy_tails() -> None:
    import random

    from generators.content_generator import _blog_post_slug_parts, _unique_slug_in_set

    rng = random.Random(404)
    s = _blog_post_slug_parts(
        "Weekly checklist (field notes)",
        rng=rng,
        city="Toronto",
        district="Liberty Village",
        post_type="how_to",
    )
    assert "how-to" not in s
    assert s
    seen = {s}
    alt = _unique_slug_in_set(s, seen)
    assert alt not in seen
    assert len(alt) > len(s) or alt != s


def test_case_slug_seed_avoids_case_index_pattern() -> None:
    from generators.content_generator import _slugify_ascii, _unique_slug_in_set

    base = _slugify_ascii("commercial-hvac-retrofit-liberty-village", max_len=52)
    assert "case-0" not in base
    assert not base.startswith("case-")
    seen: set[str] = set()
    u1 = _unique_slug_in_set(base, seen)
    seen.add(u1)
    u2 = _unique_slug_in_set(base, seen)
    assert u1 != u2
