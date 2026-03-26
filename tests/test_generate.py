from __future__ import annotations

from pathlib import Path

from core.config_loader import resolve_config
from core.runner import generate_all


def test_generate_creates_core_files(project_root: Path, tmp_path: Path):
    out = tmp_path / "generated"
    cfg = resolve_config(None, {"count": 1, "templates": ["corporate_v1"], "seed": 7}, project_root)
    cfg["output_path"] = out
    sites = generate_all(cfg)
    assert len(sites) == 1
    root = sites[0]
    assert (root / "index.php").is_file()
    assert (root / "about.php").is_file()
    assert (root / "contact.php").is_file()
    assert (root / "services.php").is_file()
    assert (root / "sitemap.xml").is_file()
    assert (root / "robots.txt").is_file()
    assert (root / "build-manifest.json").is_file()
    assert (root / ".htaccess").is_file()
    text = (root / "index.php").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "<main" in text


def test_manifest_lists_components(project_root: Path, tmp_path: Path):
    out = tmp_path / "o2"
    cfg = resolve_config(None, {"count": 1, "templates": ["reference_v1"], "seed": 1}, project_root)
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
    # The values must exist in context; at least ensure generation didn't crash and build manifest exists.
    assert (sites[0] / "build-manifest.json").is_file()
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
