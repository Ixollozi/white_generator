from __future__ import annotations

import random
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from generators.brand_generator import generate_brand
from generators.content_generator import fill_content
from integrations.tracking import build_tracking_snippet

from core.build_manifest import write_build_manifest
from core.config_loader import merge_config
from core.exporter import (
    copy_template_static,
    copy_theme_assets,
    render_junk_page,
    write_htaccess,
    zip_site_folder,
)
from core.images_engine import apply_images
from core.noise_engine import write_noise_assets
from core.seo_engine import apply_seo, build_robots_txt, build_sitemap_xml
from core.site_builder import compose_pages
from core.site_context import SiteContext
from core.template_loader import load_template_manifest, make_template_env


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _site_seed(global_seed: int | None, index: int) -> int:
    if global_seed is not None:
        return int(global_seed) + index * 1_000_003
    return random.randrange(1, 2**31 - 1)


def _pick_template(rng: random.Random, templates_dir: Path, allowed: list[str]) -> tuple[str, Path]:
    tid = rng.choice(allowed)
    tdir = templates_dir / tid
    if not tdir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {tdir}")
    return tid, tdir


def _sanitize_site_name(raw: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", raw.strip())
    cleaned = cleaned.strip(" .-_")
    if not cleaned:
        return ""
    if cleaned.startswith("."):
        cleaned = cleaned.lstrip(".")
    return cleaned[:80]


def _build_site_dir_name(cfg: dict[str, Any], site_index: int, build_id: str, output_path: Path) -> str:
    base = _sanitize_site_name(str(cfg.get("site_name") or ""))
    if not base:
        return f"site_{site_index:04d}_{build_id}"
    # For batch generation use predictable suffixes.
    if int(cfg.get("count") or 1) > 1:
        name = f"{base}_{site_index + 1:03d}"
    else:
        name = base
    candidate = name
    i = 2
    while (output_path / candidate).exists():
        candidate = f"{name}_{i}"
        i += 1
    return candidate


def generate_one_site(
    cfg: dict[str, Any],
    site_index: int,
    rng: random.Random,
) -> Path:
    project_root: Path = cfg["project_root"]
    templates_dir: Path = cfg["templates_dir"]
    components_dir: Path = cfg["components_dir"]
    allowed = list(cfg.get("templates") or ["corporate_v1"])
    template_id, template_dir = _pick_template(rng, templates_dir, allowed)
    manifest = load_template_manifest(template_dir)
    page_ext = str(manifest.get("page_extension") or "php")

    all_page_keys = list((manifest.get("pages") or {}).keys())
    filter_pages = cfg.get("pages")
    if filter_pages:
        page_keys = [k for k in filter_pages if k in all_page_keys]
        if not page_keys:
            page_keys = all_page_keys
    else:
        page_keys = all_page_keys

    manifest_pages = {k: v for k, v in (manifest.get("pages") or {}).items() if k in page_keys}
    manifest_for_build = {**manifest, "pages": manifest_pages}

    build_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    site_name = _build_site_dir_name(cfg, site_index, build_id, cfg["output_path"])
    site_dir: Path = cfg["output_path"] / site_name
    site_dir.mkdir(parents=True, exist_ok=True)

    ctx = SiteContext()
    ctx.meta.update(
        {
            "build_id": build_id,
            "template_id": template_id,
            "site_index": site_index,
        }
    )

    brand_cfg = cfg.get("brand") if isinstance(cfg.get("brand"), dict) else None
    ctx.brand.update(generate_brand(rng, brand_cfg=brand_cfg))
    ctx.content.update(fill_content(rng, ctx.brand, cfg["data_dir"]))

    ctx.images.update(apply_images(site_dir=site_dir, assets_dir=cfg["assets_dir"], images_cfg=cfg.get("images")))

    integ_cfg = cfg.get("integrations") or {}
    ctx.integrations["tracking_html"] = build_tracking_snippet(integ_cfg)

    flat_for_seo = {**ctx.brand, **ctx.content}
    seo_block = apply_seo(flat_for_seo, page_keys, page_ext)
    ctx.seo.update(seo_block)

    strict = bool(cfg.get("strict_components"))
    html_by_page = compose_pages(
        ctx,
        rng,
        template_dir,
        manifest_for_build,
        components_dir,
        strict=strict,
    )

    theme = str(cfg.get("theme") or "default")
    copy_theme_assets(cfg["assets_dir"], theme, site_dir)
    copy_template_static(template_dir, site_dir)

    for key, html in html_by_page.items():
        fname = ctx.seo["pages"][key]["path"]
        (site_dir / fname).write_text(html, encoding="utf-8")

    noise_cfg = cfg.get("noise") or {}
    noise_files = write_noise_assets(site_dir, rng, noise_cfg)
    ctx.noise["generated_files"] = noise_files

    env = make_template_env(template_dir)
    render_vars = ctx.render_vars()
    junk_keys = list(noise_cfg.get("junk_pages") or [])
    legal_titles = {
        "privacy-policy": "Privacy Policy",
        "terms-of-service": "Terms of Service",
        "cookie-policy": "Cookie Policy",
    }
    for junk in junk_keys:
        title = legal_titles.get(junk, junk.replace("-", " ").title())
        body = (
            f"This page describes how {ctx.brand.get('brand_name', 'the company')} "
            f"handles matters related to {title.lower()}. Update this text before production use."
        )
        legal_html = render_junk_page(
            env,
            "legal_page.html",
            {**render_vars, "legal_title": title, "legal_body": body},
        )
        (site_dir / f"{junk}.{page_ext}").write_text(legal_html, encoding="utf-8")

    not_found_html = render_junk_page(
        env,
        "404.html",
        {
            **render_vars,
            "legal_title": "Page not found",
            "legal_body": "The page you are looking for does not exist.",
        },
    )
    (site_dir / f"404.{page_ext}").write_text(not_found_html, encoding="utf-8")

    base_url = str(cfg.get("base_url") or "https://example.com").rstrip("/")
    paths: list[str] = []
    for k in page_keys:
        paths.append("/" + ctx.seo["pages"][k]["path"])
    for junk in junk_keys:
        paths.append(f"/{junk}.{page_ext}")

    seo_flags = cfg.get("seo") or {}
    if seo_flags.get("generate_sitemap", True):
        (site_dir / "sitemap.xml").write_text(
            build_sitemap_xml(base_url, paths),
            encoding="utf-8",
        )
    if seo_flags.get("generate_robots", True):
        (site_dir / "robots.txt").write_text(
            build_robots_txt(base_url, "/sitemap.xml"),
            encoding="utf-8",
        )

    write_htaccess(site_dir)

    seed_used = cfg.get("_per_site_seed")
    manifest_payload = {
        "build_id": build_id,
        "template_id": template_id,
        "seed": seed_used,
        "brand_name": ctx.brand.get("brand_name"),
        "pages": ctx.structure.get("pages"),
        "noise": ctx.noise,
        "base_url": base_url,
    }
    write_build_manifest(site_dir, manifest_payload)

    if cfg.get("zip_each_site"):
        zip_site_folder(site_dir, site_dir.with_suffix(".zip"))

    return site_dir


def generate_all(
    cfg: dict[str, Any],
    on_progress: Callable[[int, int, Path], None] | None = None,
) -> list[Path]:
    count = int(cfg.get("count") or 1)
    cfg["output_path"].mkdir(parents=True, exist_ok=True)
    global_seed = cfg.get("seed")
    if global_seed is not None:
        global_seed = int(global_seed)

    out: list[Path] = []
    for i in range(count):
        per_seed = _site_seed(global_seed, i)
        cfg_merged = merge_config(cfg, {"_per_site_seed": per_seed})
        rng = random.Random(per_seed)
        site_path = generate_one_site(cfg_merged, i, rng)
        out.append(site_path)
        if on_progress is not None:
            on_progress(i + 1, count, site_path)
    return out


def run_generation(
    cfg: dict[str, Any],
    on_progress: Callable[[int, int, Path], None] | None = None,
) -> list[Path]:
    """Programmatic entry point (CLI and web UI)."""
    return generate_all(cfg, on_progress=on_progress)
