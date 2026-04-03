from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

from jinja2 import Environment

from core.component_loader import ComponentPick, pick_component
from core.site_context import SiteContext
from core.template_loader import make_template_env, render_string


_PROF_PROMO_ONE_SITE: frozenset[str] = frozenset(
    {"legal", "consulting", "medical", "dental", "accounting"},
)


def _promo_banner_for_page(render_vars: dict[str, Any], page_key: str) -> str:
    pool = render_vars.get("promo_banner_pool")
    if not isinstance(pool, list) or len(pool) < 2:
        return str(render_vars.get("promo_banner_text") or "").strip()
    ident = str(render_vars.get("generation_identity") or render_vars.get("brand_name") or "")
    vid = str(render_vars.get("vertical_id") or "").strip()
    seed_key = ident if vid in _PROF_PROMO_ONE_SITE else f"{page_key}|{ident}"
    h = int(
        hashlib.sha256(f"promo|{seed_key}".encode("utf-8")).hexdigest(),
        16,
    )
    return str(pool[h % len(pool)]).strip() or str(render_vars.get("promo_banner_text") or "")


def _page_href(page_key: str, ext: str) -> str:
    e = ext.strip() or "php"
    if page_key == "index":
        return "index.php" if e == "php" else f"index.{e}"
    return f"{page_key}.php" if e == "php" else f"{page_key}.{e}"


def _resolved_page_href(page_key: str, ext: str, render_vars: dict[str, Any]) -> str:
    sp = render_vars.get("seo_pages")
    if isinstance(sp, dict):
        meta = sp.get(page_key)
        if isinstance(meta, dict):
            pth = str(meta.get("path") or "").strip()
            if pth:
                return pth
    return _page_href(page_key, ext)


def breadcrumb_items(page_key: str, render_vars: dict[str, Any]) -> list[dict[str, str | None]]:
    if page_key == "index":
        return []
    ext = str(render_vars.get("page_extension") or "php")
    home_h = _resolved_page_href("index", ext, render_vars)
    ind_lbl = str(render_vars.get("industries_page_header") or "Industries").strip() or "Industries"
    labels_hrefs: dict[str, tuple[str, str]] = {
        "about": (str(render_vars.get("about_page_header") or "About"), _resolved_page_href("about", ext, render_vars)),
        "contact": (str(render_vars.get("contact_page_header") or "Contact"), _resolved_page_href("contact", ext, render_vars)),
        "services": (str(render_vars.get("services_heading") or "Services"), _resolved_page_href("services", ext, render_vars)),
        "blog": (str(render_vars.get("blog_page_header") or "Blog"), _resolved_page_href("blog", ext, render_vars)),
        "faq": (str(render_vars.get("faq_page_header") or "FAQ"), _resolved_page_href("faq", ext, render_vars)),
        "team": ("Team", _resolved_page_href("team", ext, render_vars)),
        "testimonials": ("Testimonials", _resolved_page_href("testimonials", ext, render_vars)),
        "pricing": ("Pricing", _resolved_page_href("pricing", ext, render_vars)),
        "process": ("Our Process", _resolved_page_href("process", ext, render_vars)),
        "portfolio": ("Portfolio", _resolved_page_href("portfolio", ext, render_vars)),
        "case_studies": ("Case studies", _resolved_page_href("case_studies", ext, render_vars)),
        "careers": ("Careers", _resolved_page_href("careers", ext, render_vars)),
        "industries": (ind_lbl, _resolved_page_href("industries", ext, render_vars)),
        "resources": (str(render_vars.get("resources_page_header") or "Resources"), _resolved_page_href("resources", ext, render_vars)),
        "service_areas": ("Service areas", _resolved_page_href("service_areas", ext, render_vars)),
    }
    if page_key not in labels_hrefs:
        return [{"label": "Home", "href": home_h}]
    label, _href = labels_hrefs[page_key]
    return [
        {"label": "Home", "href": home_h},
        {"label": label, "href": None},
    ]


def _inject_index_extras(slots: list[str], extras: list[str], before: str) -> list[str]:
    if not extras:
        return list(slots)
    s = list(slots)
    if before in s:
        i = s.index(before)
        return s[:i] + extras + s[i:]
    if "footer" in s:
        i = s.index("footer")
        return s[:i] + extras + s[i:]
    return s + extras


def _shuffle_index_slots(rng: random.Random, slots: list[str]) -> list[str]:
    """Keep nav_bar+hero (or hero alone) at top; keep contact_teaser+footer tail; shuffle middle."""
    s = list(slots)
    if len(s) <= 2:
        return s

    tail_start = None
    if "contact_teaser" in s:
        tail_start = s.index("contact_teaser")
    if tail_start is None:
        return _shuffle_middle_legacy(rng, s)

    head = s[:tail_start]
    tail = s[tail_start:]

    if len(head) <= 1:
        return head + tail

    if head[0] == "nav_bar" and len(head) > 1:
        first = head[0]
        second = head[1]
        middle = head[2:]
        rng.shuffle(middle)
        return [first, second, *middle, *tail]

    first = head[0]
    middle = head[1:]
    rng.shuffle(middle)
    return [first, *middle, *tail]


def _shuffle_middle_legacy(rng: random.Random, slots: list[str]) -> list[str]:
    if len(slots) <= 2:
        return list(slots)
    first = slots[0]
    last = slots[-1]
    middle = list(slots[1:-1])
    rng.shuffle(middle)
    return [first, *middle, last]


def _resolve_slots(
    page_key: str,
    page_def: dict[str, Any],
    meta: dict[str, Any],
) -> list[str]:
    slots = list(page_def.get("slots") or [])
    if page_key != "index":
        return slots
    extras = meta.get("index_slot_extras") or []
    before = str(meta.get("index_slot_inject_before") or "contact_teaser")
    if isinstance(extras, list) and extras:
        ex = [str(x) for x in extras if x]
        slots = _inject_index_extras(slots, ex, before)
    return slots


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
    render_vars = ctx.render_vars()
    built: dict[str, list[ComponentPick]] = {}
    structure_log: dict[str, Any] = {}
    meta = ctx.meta

    for page_key, page_def in manifest.get("pages", {}).items():
        slots = _resolve_slots(page_key, page_def, meta)
        if page_def.get("shuffle_allowed"):
            slots = _shuffle_index_slots(rng, slots)
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
        rv_page = dict(render_vars)
        rv_page["promo_banner_text"] = _promo_banner_for_page(render_vars, page_key)
        html = template.render(
            **rv_page,
            body_html=body,
            page_key=page_key,
            page_title=page_seo.get("title") or render_vars.get("brand_name", "Site"),
            page_description=page_seo.get("description") or render_vars.get("tagline", ""),
            page_canonical=page_seo.get("canonical") or "",
            json_ld_organization=ctx.seo.get("json_ld_organization") or "",
            breadcrumbs=breadcrumb_items(page_key, render_vars),
        )
        full_pages[page_key] = html

    return full_pages
