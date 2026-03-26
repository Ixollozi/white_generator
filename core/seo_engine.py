from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape


def apply_seo(
    ctx: dict[str, Any],
    pages: list[str],
    page_extension: str,
) -> dict[str, Any]:
    """Populate ctx['seo'] with per-page title/description and url list."""
    brand = ctx.get("brand_name", "Site")
    tagline = ctx.get("tagline", "")
    seo_pages: dict[str, dict[str, str]] = {}
    urls: list[str] = []

    titles = {
        "index": brand,
        "about": f"About — {brand}",
        "contact": f"Contact — {brand}",
    }
    descriptions = {
        "index": tagline,
        "about": f"Learn more about {brand}.",
        "contact": f"Reach {brand} by phone, email, or the contact form.",
    }

    for key in pages:
        fname = "index.php" if key == "index" else f"{key}.{page_extension}"
        urls.append(f"/{fname}")
        seo_pages[key] = {
            "title": titles.get(key, f"{key.title()} — {brand}"),
            "description": descriptions.get(key, tagline),
            "path": fname,
        }

    return {"pages": seo_pages, "urls": urls}


def build_sitemap_xml(base_url: str, paths: list[str]) -> str:
    base = base_url.rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for p in paths:
        loc = escape(f"{base}{p}")
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def build_robots_txt(base_url: str, sitemap_path: str = "/sitemap.xml") -> str:
    base = base_url.rstrip("/")
    sm = f"{base}{sitemap_path}" if sitemap_path.startswith("/") else f"{base}/{sitemap_path}"
    return f"User-agent: *\nAllow: /\n\nSitemap: {sm}\n"
