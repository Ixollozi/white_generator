from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "count": 1,
    "templates": ["corporate_v1"],
    "pages": None,
    "base_url": "https://example.com",
    "output_dir": "output",
    "site_name": None,
    "vertical": None,
    "theme": "default",
    "seed": None,
    "strict_components": False,
    "brand": {
        "domain_mode": "none",  # none|brand_tld|random_tld
        "tlds": ["com", "net", "org"],
        "custom_domain": None,
    },
    "seo": {
        "generate_sitemap": True,
        "generate_robots": True,
        "generate_keywords": False,
    },
    "noise": {
        "extra_css_max": 3,
        "extra_js_max": 3,
        "junk_pages": [
            "privacy-policy",
            "terms-of-service",
            "cookie-policy",
            "refund-policy",
            "shipping-policy",
        ],
        "attach_assets": False,
        "randomize_classes": False,
        "randomize_ids": False,
        "id_safelist": ["cookie-consent", "cookie-ok"],
    },
    "images": {
        "mode": "none",  # none|web|upload
        "image_source": None,  # unset + mode none → placeholder (local); web → picsum; upload+pack → pack
        "web_sources": [],
        "asset_pack_id": None,
        "count": 3,
    },
    "integrations": {
        "offer_link": "",
    },
    "legal": {
        "mode": "production",  # draft|production
    },
    "zip_each_site": False,
    # When False (default), build-manifest.json is not written into the site folder (safer for public deploy).
    "write_build_manifest": False,
}


def load_config_file(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data


def merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = {**base}
    for k, v in overrides.items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = {**out[k], **v}
            out[k] = merged
        else:
            out[k] = v
    return out


def resolve_config(
    config_path: Path | None,
    cli_overrides: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    cfg = {**DEFAULT_CONFIG}
    if config_path and config_path.is_file():
        cfg = merge_config(cfg, load_config_file(config_path))
    cfg = merge_config(cfg, cli_overrides)
    cfg["project_root"] = project_root
    cfg["data_dir"] = project_root / "data"
    cfg["components_dir"] = project_root / "components"
    cfg["templates_dir"] = project_root / "templates"
    cfg["assets_dir"] = project_root / "assets"
    out_dir = cfg.get("output_dir") or "output"
    cfg["output_path"] = project_root / out_dir
    return cfg
