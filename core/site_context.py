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
        return out
