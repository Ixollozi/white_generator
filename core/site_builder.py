from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from jinja2 import Environment

from core.component_loader import ComponentPick, pick_component
from core.site_context import SiteContext
from core.template_loader import make_template_env, render_string


def _shuffle_middle(rng: random.Random, slots: list[str]) -> list[str]:
    if len(slots) <= 2:
        return list(slots)
    first = slots[0]
    last = slots[-1]
    middle = list(slots[1:-1])
    rng.shuffle(middle)
    return [first, *middle, last]


def compose_pages(
    ctx: SiteContext,
    rng: random.Random,
    template_dir: Path,
    manifest: dict[str, Any],
    components_dir: Path,
    strict: bool,
) -> dict[str, str]:
    """
    Returns map page_key -> full HTML document string (before SEO/noise file passes).
    """
    env = make_template_env(template_dir)
    pages_cfg = manifest.get("pages") or {}
    render_vars = ctx.render_vars()
    built: dict[str, list[ComponentPick]] = {}
    structure_log: dict[str, Any] = {}

    for page_key, page_def in pages_cfg.items():
        slots = list(page_def.get("slots") or [])
        if page_def.get("shuffle_allowed"):
            slots = _shuffle_middle(rng, slots)
        picks: list[ComponentPick] = []
        for slot in slots:
            pick = pick_component(rng, components_dir, slot, render_vars, strict=strict)
            picks.append(pick)
        built[page_key] = picks
        structure_log[page_key] = [{"type": p.component_type, "variant": p.variant_file} for p in picks]

    ctx.structure["pages"] = structure_log

    page_bodies: dict[str, str] = {}
    for page_key, picks in built.items():
        fragments: list[str] = []
        for p in picks:
            vars_with_page = {**render_vars, "page_key": page_key}
            fragments.append(render_string(env, p.html, vars_with_page))
        page_bodies[page_key] = "\n".join(fragments)

    layout_name = manifest.get("layout") or "layout.html"
    template = env.get_template(layout_name)
    full_pages: dict[str, str] = {}
    seo_pages = ctx.seo.get("pages") or {}

    for page_key, body in page_bodies.items():
        page_seo = seo_pages.get(page_key) or {}
        html = template.render(
            **render_vars,
            body_html=body,
            page_key=page_key,
            page_title=page_seo.get("title") or render_vars.get("brand_name", "Site"),
            page_description=page_seo.get("description") or render_vars.get("tagline", ""),
        )
        full_pages[page_key] = html

    return full_pages
