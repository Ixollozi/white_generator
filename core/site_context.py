from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SiteContext:
    """Single source of truth for one generated site (mutable during pipeline stages)."""

    brand: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    seo: dict[str, Any] = field(default_factory=dict)
    noise: dict[str, Any] = field(default_factory=dict)
    images: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    integrations: dict[str, Any] = field(default_factory=dict)

    def render_vars(self) -> dict[str, Any]:
        """Flat dict for Jinja: brand.*, content.*, seo.*, integrations.*, meta.*."""
        out: dict[str, Any] = {}
        out.update(self.brand)
        out.update(self.content)
        out.update({f"seo_{k}": v for k, v in self.seo.items()})
        out["images"] = self.images
        out["integrations"] = self.integrations
        out["meta"] = self.meta
        nav = self.meta.get("nav_items")
        if isinstance(nav, list) and nav:
            out["nav_items"] = nav
        else:
            out["nav_items"] = [
                {"href": "index.php", "label": "Home"},
                {"href": "about.php", "label": "About"},
                {"href": "services.php", "label": "Services"},
                {"href": "contact.php", "label": "Contact"},
            ]
        pl = self.meta.get("policy_links")
        if isinstance(pl, list) and pl:
            out["policy_links"] = pl
        bec = self.meta.get("body_extra_class")
        out["body_extra_class"] = str(bec).strip() if bec else ""
        pe = self.meta.get("page_extension")
        out["page_extension"] = str(pe).strip() if isinstance(pe, str) and pe.strip() else "php"
        sb = self.meta.get("site_base_url")
        if isinstance(sb, str) and sb.strip():
            out["site_base_url"] = sb.strip().rstrip("/")
        else:
            out["site_base_url"] = ""
        pk = self.meta.get("page_keys")
        ext = out["page_extension"]
        if isinstance(pk, list) and "blog" in pk:
            out["insights_href"] = f"blog.{ext}"
            out["insights_label"] = "Blog"
        elif isinstance(pk, list) and "resources" in pk:
            out["insights_href"] = f"resources.{ext}"
            out["insights_label"] = "Resources"
        else:
            out["insights_href"] = ""
            out["insights_label"] = "Blog"
        out["core_stylesheet_href"] = str(self.meta.get("core_stylesheet_href") or "css/core.css")
        out["layout_stylesheet_href"] = str(self.meta.get("layout_stylesheet_href") or "css/layout.css")
        out["vendor_stylesheet_href"] = str(self.meta.get("vendor_stylesheet_href") or "css/vendor.css")
        se = self.meta.get("stylesheet_extras")
        out["stylesheet_extras"] = list(se) if isinstance(se, list) else []
        return out
