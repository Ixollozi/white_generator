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
        return out
