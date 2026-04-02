from __future__ import annotations

import json
import random
import re
import secrets
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from generators.brand_generator import generate_brand
from generators.content_generator import fill_content, load_verticals, pick_vertical
from integrations.tracking import build_tracking_snippet

from core.build_manifest import write_build_manifest
from core.ui_site_meta import write_ui_site_meta
from core.config_loader import merge_config
from core.exporter import (
    copy_template_static,
    copy_theme_assets,
    render_junk_page,
    write_htaccess,
    zip_site_folder,
)
from core.gallery_images import materialize_gallery_images
from core.html_noise import apply_html_noise
from core.images_engine import apply_images
from core.legal_copy import legal_document_html, disclaimer_page_html, accessibility_page_html
from core.noise_engine import write_noise_assets
from core.seo_engine import (
    apply_seo,
    build_robots_txt,
    build_sitemap_xml,
    blog_post_json_ld,
    news_article_json_ld,
    register_auxiliary_pages_seo,
    register_blog_extra_pages,
    register_case_study_pages,
    register_product_pages,
    register_news_extra_pages,
)
from core.trust_policies import service_policy_html
from core.newsroom_policies import newsroom_policy_html
from core.site_builder import compose_pages
from core.site_context import SiteContext
from core.public_url import effective_public_base_url
from core.theme_pack import load_theme_pack, theme_folder_for_vertical
from core.template_loader import load_template_manifest, make_template_env
from core.trust_policies import trust_policy_html
from core.visual_assets import materialize_site_visuals


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _site_seed(global_seed: int | None, index: int) -> int:
    if global_seed is not None:
        return int(global_seed) + index * 1_000_003
    return random.randrange(1, 2**31 - 1)


def _finalize_page_keys(
    rng: random.Random,
    page_keys: list[str],
    all_page_keys: list[str],
) -> list[str]:
    """Mutual exclusions + guarantees so sites differ (services vs industries, blog vs resources)."""
    pk = [k for k in page_keys if k in all_page_keys]
    if "services" in pk and "industries" in pk:
        pk.remove(rng.choice(["industries", "services"]))
    if "services" not in pk and "industries" not in pk:
        pk.append(rng.choice(["services", "industries"]))
    if "blog" in pk and "resources" in pk:
        pk.remove(rng.choice(["blog", "resources"]))
    if "blog" not in pk and "resources" not in pk:
        pk.append(rng.choice(["blog", "resources"]))
    return pk


def _adjust_nav_for_structure(
    nav: list[dict[str, str]],
    page_keys: list[str],
    page_ext: str,
) -> None:
    ext = page_ext.strip() or "php"
    for item in nav:
        href = str(item.get("href") or "")
        if href == f"services.{ext}" and "services" not in page_keys and "industries" in page_keys:
            item["href"] = f"industries.{ext}"
            if str(item.get("label") or "").strip().lower() in ("services", "what we do"):
                item["label"] = "Industries"
        if href == f"blog.{ext}" and "blog" not in page_keys and "resources" in page_keys:
            item["href"] = f"resources.{ext}"
            if str(item.get("label") or "").strip().lower() == "blog":
                item["label"] = "Resources"


def _augment_nav_items(
    nav: list[dict[str, Any]],
    page_keys: list[str],
    page_ext: str,
    vertical_id: str | None = None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for x in nav:
        if not isinstance(x, dict):
            continue
        href = str(x.get("href") or "").strip()
        label = str(x.get("label") or "").strip()
        if href and label:
            out.append({"href": href, "label": label})
    hrefs = {x["href"] for x in out}
    _optional_pages: list[tuple[str, str]] = [
        ("blog", "Blog"),
        ("faq", "FAQ"),
        ("team", "Team"),
        ("testimonials", "Testimonials"),
        ("pricing", "Pricing"),
        ("process", "Process"),
        ("portfolio", "Portfolio"),
        ("case_studies", "Case studies"),
        ("careers", "Careers"),
        ("industries", "Industries"),
        ("resources", "Resources"),
        ("service_areas", "Service areas"),
    ]
    for key, label in _optional_pages:
        if key in page_keys:
            h = f"{key}.{page_ext}"
            if h not in hrefs:
                out.append({"href": h, "label": label})
                hrefs.add(h)
    if (vertical_id or "").strip() == "news":
        ha = f"authors.{page_ext}"
        if ha not in hrefs:
            out.append({"href": ha, "label": "Staff"})
            hrefs.add(ha)
    return out


def _pick_template(rng: random.Random, templates_dir: Path, allowed: list[str]) -> tuple[str, Path]:
    tid = rng.choice(allowed)
    tdir = templates_dir / tid
    if not tdir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {tdir}")
    return tid, tdir


def _write_brand_site_extras(site_dir: Path, brand: dict[str, Any]) -> None:
    name = str(brand.get("brand_name") or "Site")
    letter = (name.strip()[:1] or "S").upper()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect fill="#0f172a" width="64" height="64" rx="14"/>'
        f'<text x="32" y="41" font-size="34" text-anchor="middle" fill="#f8fafc" '
        f'font-family="Segoe UI,system-ui,sans-serif">{letter}</text></svg>'
    )
    (site_dir / "favicon.svg").write_text(svg, encoding="utf-8")
    icons: list[dict[str, str]] = []
    if (site_dir / "icon-192.png").is_file():
        icons.append({"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"})
    if (site_dir / "favicon-32x32.png").is_file():
        icons.append({"src": "favicon-32x32.png", "sizes": "32x32", "type": "image/png"})
    icons.append({"src": "favicon.svg", "sizes": "any", "type": "image/svg+xml"})
    manifest = {
        "name": name,
        "short_name": name[:12],
        "icons": icons,
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0f172a",
    }
    (site_dir / "site.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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

    all_pages = manifest.get("pages") or {}
    all_page_keys = list(all_pages.keys())
    filter_pages = cfg.get("pages")
    if filter_pages:
        page_keys = [k for k in filter_pages if k in all_page_keys]
        if not page_keys:
            page_keys = all_page_keys
    else:
        required = [k for k, v in all_pages.items() if isinstance(v, dict) and v.get("required")]
        optional = [k for k in all_page_keys if k not in required]
        target_total = rng.randint(6, min(12, len(all_page_keys)))
        n_opt = max(0, min(len(optional), target_total - len(required)))
        chosen_opt = rng.sample(optional, n_opt) if n_opt else []
        page_keys = required + chosen_opt
        page_keys = _finalize_page_keys(rng, page_keys, all_page_keys)

    manifest_pages = {k: v for k, v in all_pages.items() if k in page_keys}
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
            "page_extension": page_ext,
        }
    )

    brand_cfg = cfg.get("brand") if isinstance(cfg.get("brand"), dict) else None
    verticals = load_verticals(cfg["data_dir"])
    vdef = pick_vertical(rng, cfg.get("vertical"), verticals)
    # Vertical-specific page gating: some templates define pages that should only exist
    # for certain verticals (e.g., shop/cart/checkout only for clothing).
    vid_gate = str(vdef.get("id") or "").strip()
    if vid_gate != "clothing":
        page_keys = [k for k in page_keys if k not in ("shop", "cart", "checkout")]
        manifest_pages = {k: v for k, v in (manifest.get("pages") or {}).items() if k in page_keys}
        manifest_for_build = {**manifest, "pages": manifest_pages}
    theme_pack = load_theme_pack(project_root, str(vdef.get("id") or ""))
    nav_built = _augment_nav_items(
        theme_pack["nav_items"],
        page_keys,
        page_ext,
        str(vdef.get("id") or ""),
    )
    _adjust_nav_for_structure(nav_built, page_keys, page_ext)
    ctx.meta["nav_items"] = nav_built
    ctx.meta["index_slot_extras"] = theme_pack["index_extras"]
    ctx.meta["index_slot_inject_before"] = theme_pack["inject_before"]
    ctx.meta["theme_pack_folder"] = theme_folder_for_vertical(
        project_root,
        str(vdef.get("id") or ""),
    )
    # Optional homepage sections (trust + local signals); skip news/clothing storefront feel.
    if str(vdef.get("id") or "").strip() not in ("news", "clothing"):
        ix_ex = list(ctx.meta.get("index_slot_extras") or [])
        pool_ix = ["usp_strip", "clients_strip", "process_preview", "service_area_list"]
        rng.shuffle(pool_ix)
        n_ix = rng.randint(1, min(3, len(pool_ix)))
        for slot in pool_ix[:n_ix]:
            if slot not in ix_ex:
                ix_ex.append(slot)
        ctx.meta["index_slot_extras"] = ix_ex
    if rng.random() < 0.55:
        bec = str(ctx.meta.get("body_extra_class") or "").strip()
        sticky = "header-sticky" if rng.random() < 0.5 else "site-sticky-header"
        ctx.meta["body_extra_class"] = f"{bec} {sticky}".strip()

    per_seed = cfg.get("_per_site_seed")
    site_identity = f"{build_id}|{site_index}|{per_seed}"
    ctx.brand.update(
        generate_brand(
            rng,
            brand_cfg=brand_cfg,
            vertical=vdef,
            theme_pack=theme_pack,
            site_identity=site_identity,
        ),
    )
    news_opts = None
    if isinstance(cfg, dict):
        news_opts = {
            k: cfg[k]
            for k in ("news_article_count", "news_default_article_kind", "news_style_mix")
            if k in cfg and cfg[k] is not None
        }
        if not news_opts:
            news_opts = None
    ctx.content.update(
        fill_content(
            rng,
            ctx.brand,
            cfg["data_dir"],
            vertical=vdef,
            theme_pack=theme_pack,
            news_options=news_opts,
        ),
    )
    _img_cfg = cfg.get("images") if isinstance(cfg.get("images"), dict) else {}
    materialize_gallery_images(site_dir, ctx.content, rng, ctx.brand, images_cfg=_img_cfg)
    materialize_site_visuals(
        site_dir,
        ctx.brand,
        ctx.content,
        rng,
        images_cfg=_img_cfg,
        assets_dir=cfg.get("assets_dir"),
    )

    ctx.images.update(apply_images(site_dir=site_dir, assets_dir=cfg["assets_dir"], images_cfg=cfg.get("images")))

    integ_cfg = cfg.get("integrations") or {}
    ctx.integrations["tracking_html"] = build_tracking_snippet(integ_cfg, fingerprint_salt=build_id)

    effective_base = effective_public_base_url(str(cfg.get("base_url") or ""), ctx.brand)
    ctx.meta["site_base_url"] = effective_base.rstrip("/")
    flat_for_seo = {**ctx.brand, **ctx.content}
    noise_cfg = cfg.get("noise") or {}
    junk_keys_cfg = list(noise_cfg.get("junk_pages") or [])
    seo_block = apply_seo(flat_for_seo, page_keys, page_ext, effective_base)
    ctx.seo.update(seo_block)
    # Build policy links (footer) and guarantee those pages are generated.
    vid = str(ctx.content.get("vertical_id") or "").strip()

    def _href(slug: str) -> str:
        return f"{slug}.php" if page_ext == "php" else f"{slug}.{page_ext}"

    _base_policies = [
        {"href": _href("privacy-policy"), "label": "Privacy"},
        {"href": _href("terms-of-service"), "label": "Terms"},
        {"href": _href("cookie-policy"), "label": "Cookies"},
    ]
    if vid == "news":
        policy_links = _base_policies + [
            {"href": _href("corrections-policy"), "label": "Corrections"},
            {"href": _href("ethics-policy"), "label": "Ethics"},
            {"href": _href("republishing-policy"), "label": "Republishing"},
        ]
    elif vid == "clothing":
        policy_links = _base_policies + [
            {"href": _href("refund-policy"), "label": "Refunds"},
            {"href": _href("shipping-policy"), "label": "Shipping"},
        ]
    elif vid in ("cafe_restaurant", "fitness", "cleaning"):
        policy_links = _base_policies + [
            {"href": _href("refund-policy"), "label": "Cancellations"},
        ]
    else:
        policy_links = list(_base_policies)
    # Randomly add disclaimer and/or accessibility pages
    if rng.random() < 0.4:
        policy_links.append({"href": _href("disclaimer"), "label": "Disclaimer"})
    if rng.random() < 0.3:
        policy_links.append({"href": _href("accessibility"), "label": "Accessibility"})
    ctx.meta["policy_links"] = policy_links

    policy_slugs = [x["href"].rsplit(".", 1)[0] for x in policy_links if isinstance(x, dict) and x.get("href")]
    junk_keys_pre = [x for x in junk_keys_cfg if isinstance(x, str) and x.strip()]
    for slug in policy_slugs:
        if slug not in junk_keys_pre:
            junk_keys_pre.append(slug)
    # Enforce vertical semantics even if config includes extra junk pages.
    if vid == "news":
        junk_keys_pre = [x for x in junk_keys_pre if x not in ("refund-policy", "shipping-policy")]

    register_auxiliary_pages_seo(ctx.seo, flat_for_seo, junk_keys_pre, page_ext, effective_base)
    news_posts = ctx.content.get("blog_posts")
    if str(ctx.content.get("vertical_id") or "") == "news" and isinstance(news_posts, list):
        register_news_extra_pages(ctx.seo, flat_for_seo, news_posts, page_ext, effective_base)
    else:
        non_news_posts = ctx.content.get("blog_posts")
        if isinstance(non_news_posts, list) and non_news_posts:
            register_blog_extra_pages(ctx.seo, flat_for_seo, non_news_posts, page_ext, effective_base)
        cs_list = ctx.content.get("case_studies")
        if "case_studies" in page_keys and isinstance(cs_list, list) and cs_list:
            register_case_study_pages(ctx.seo, flat_for_seo, cs_list, page_ext, effective_base)
    # Clothing storefront pages (shop/cart/checkout; catalog + details on shop)
    if str(ctx.content.get("vertical_id") or "") == "clothing":
        prods = ctx.content.get("products")
        if isinstance(prods, list) and prods:
            register_product_pages(ctx.seo, flat_for_seo, page_ext, effective_base)

    # Lightweight content validation (non-fatal; stored in build manifest)
    validations: list[dict[str, Any]] = []
    posts_any = ctx.content.get("blog_posts")
    if isinstance(posts_any, list) and posts_any:
        missing_fields = 0
        missing_links = 0
        bad_length = 0
        for p in posts_any:
            if not isinstance(p, dict):
                continue
            for k in ("anchor", "title", "date_iso"):
                if not str(p.get(k) or "").strip():
                    missing_fields += 1
            # Require at least 2 sources if present (news always has)
            srcs = p.get("sources")
            if not isinstance(srcs, list) or len(srcs) < 2:
                missing_fields += 1
            secs = p.get("article_sections_html")
            if isinstance(secs, list) and secs:
                txt = " ".join(
                    " ".join(str(x) for x in (s.get("paragraphs_html") or []) if isinstance(x, str))
                    for s in secs
                    if isinstance(s, dict)
                )
                # external link check (in-body)
                if txt.count("http") < 2:
                    missing_links += 1
                # word-ish length heuristic
                wordish = len(txt.replace("<", " ").replace(">", " ").split())
                if wordish < 780 or wordish > 1650:
                    bad_length += 1
            else:
                missing_fields += 1
        validations.append(
            {
                "type": "blog_posts",
                "count": len(posts_any),
                "missing_fields": missing_fields,
                "missing_external_links": missing_links,
                "bad_length_estimate": bad_length,
            }
        )
    ctx.structure.setdefault("validations", validations)

    # Duplicate prevention: titles/anchors must be unique within a site.
    posts_any = ctx.content.get("blog_posts")
    if isinstance(posts_any, list) and posts_any:
        seen_a: set[str] = set()
        seen_t: set[str] = set()
        dup_a = 0
        dup_t = 0
        for p in posts_any:
            if not isinstance(p, dict):
                continue
            a = str(p.get("anchor") or "").strip()
            t = str(p.get("title") or "").strip().lower()
            if a:
                if a in seen_a:
                    dup_a += 1
                seen_a.add(a)
            if t:
                if t in seen_t:
                    dup_t += 1
                seen_t.add(t)
        ctx.structure.setdefault("validations", []).append(
            {"type": "dedup", "dup_anchors": dup_a, "dup_titles": dup_t}
        )
        # Fail hard in production, and also when strict_components is enabled.
        if dup_a or dup_t:
            legal_cfg = cfg.get("legal") if isinstance(cfg.get("legal"), dict) else {}
            legal_mode = str((legal_cfg or {}).get("mode") or "production").strip().lower()
            if legal_mode == "production" or bool(cfg.get("strict_components")):
                raise ValueError(f"Duplicate blog posts detected: dup_anchors={dup_a} dup_titles={dup_t}")

    strict = bool(cfg.get("strict_components"))
    html_by_page = compose_pages(
        ctx,
        rng,
        template_dir,
        manifest_for_build,
        components_dir,
        strict=strict,
    )

    noise_apply = bool(noise_cfg.get("randomize_classes")) or bool(noise_cfg.get("randomize_ids"))
    noise_tok = secrets.token_hex(4) if noise_apply else ""
    if noise_apply:
        html_by_page = {
            k: apply_html_noise(v, rng, noise_cfg, noise_tok) for k, v in html_by_page.items()
        }
        # Guardrails: randomization must not break required behavior hooks.
        if bool(noise_cfg.get("randomize_ids")):
            required_ids = {"cookie-consent", "cookie-ok"}
            for key, html in html_by_page.items():
                missing = [rid for rid in required_ids if f'id="{rid}"' not in html]
                if missing:
                    # In strict environments we'd raise; for now, fail-fast to avoid shipping broken UX.
                    raise ValueError(f"Noise broke required ids on page={key}: {missing}")

    theme = str(cfg.get("theme") or "default")
    copy_theme_assets(cfg["assets_dir"], theme, site_dir)
    copy_template_static(template_dir, site_dir)
    _write_brand_site_extras(site_dir, ctx.brand)

    for key, html in html_by_page.items():
        fname = ctx.seo["pages"][key]["path"]
        (site_dir / fname).write_text(html, encoding="utf-8")

    if str(ctx.content.get("vertical_id") or "") == "news" and isinstance(news_posts, list):
        news_env = make_template_env(template_dir)
        layout_tpl = news_env.get_template("layout.html")
        rv_news = ctx.render_vars()
        flat_news = {**ctx.brand, **ctx.content}
        for post in news_posts:
            if not isinstance(post, dict):
                continue
            anchor = str(post.get("anchor") or "").strip()
            if not anchor:
                continue
            seo_key = f"article-{anchor}"
            meta = (ctx.seo.get("pages") or {}).get(seo_key) or {}
            body_html = news_env.get_template("article_body.html").render(**rv_news, post=post)
            canon = str(meta.get("canonical") or f"{effective_base}/article-{anchor}.{page_ext}")
            ptitle = str(meta.get("title") or f"{post.get('title')} — {ctx.brand.get('brand_name')}")
            pdesc = str(meta.get("description") or "")[:320]
            og_art = (post.get("post_image_src") or rv_news.get("og_image_src") or "").strip()
            rv_art = dict(rv_news)
            rv_art.update(
                {
                    "body_html": body_html,
                    "page_key": seo_key,
                    "page_title": ptitle,
                    "page_description": pdesc,
                    "page_canonical": canon,
                    "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                    "json_ld_news_article": news_article_json_ld(
                        effective_base,
                        flat_news,
                        post,
                        page_ext,
                    ),
                    "breadcrumbs": [
                        {"label": "Home", "href": "index.php" if page_ext == "php" else f"index.{page_ext}"},
                        {
                            "label": str(rv_news.get("blog_page_header") or "Newsroom"),
                            "href": f"blog.{page_ext}",
                        },
                        {"label": str(post.get("title") or "Article")[:72], "href": None},
                    ],
                    "og_image_src": og_art,
                    "page_og_type": "article",
                },
            )
            art_html = layout_tpl.render(**rv_art)
            if noise_apply:
                art_html = apply_html_noise(art_html, rng, noise_cfg, noise_tok)
            out_name = str(meta.get("path") or f"article-{anchor}.{page_ext}")
            (site_dir / out_name).write_text(art_html, encoding="utf-8")

        ap_meta = (ctx.seo.get("pages") or {}).get("authors") or {}
        authors_html_body = news_env.get_template("authors_body.html").render(**rv_news)
        rv_auth = dict(rv_news)
        rv_auth.update(
            {
                "body_html": authors_html_body,
                "page_key": "authors",
                "page_title": str(ap_meta.get("title") or f"Staff — {ctx.brand.get('brand_name')}"),
                "page_description": str(ap_meta.get("description") or ""),
                "page_canonical": str(ap_meta.get("canonical") or f"{effective_base}/authors.{page_ext}"),
                "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                "json_ld_news_article": "",
                "breadcrumbs": [
                    {"label": "Home", "href": "index.php" if page_ext == "php" else f"index.{page_ext}"},
                    {"label": "Staff", "href": None},
                ],
                "og_image_src": rv_news.get("og_image_src") or "",
                "page_og_type": "website",
            },
        )
        authors_page = layout_tpl.render(**rv_auth)
        if noise_apply:
            authors_page = apply_html_noise(authors_page, rng, noise_cfg, noise_tok)
        (site_dir / str(ap_meta.get("path") or f"authors.{page_ext}")).write_text(authors_page, encoding="utf-8")

    # Non-news: write dedicated post pages (post-<anchor>.<ext>)
    if str(ctx.content.get("vertical_id") or "") != "news":
        posts = ctx.content.get("blog_posts")
        if isinstance(posts, list) and posts:
            env_posts = make_template_env(template_dir)
            layout_tpl = env_posts.get_template("layout.html")
            body_tpl = env_posts.get_template("blog_article_body.html")
            rv = ctx.render_vars()
            flat = {**ctx.brand, **ctx.content}
            for post in posts:
                if not isinstance(post, dict):
                    continue
                anchor = str(post.get("anchor") or "").strip()
                if not anchor:
                    continue
                seo_key = f"post-{anchor}"
                meta = (ctx.seo.get("pages") or {}).get(seo_key) or {}
                body_html = body_tpl.render(**rv, post=post)
                canon = str(meta.get("canonical") or f"{effective_base}/post-{anchor}.{page_ext}")
                ptitle = str(meta.get("title") or f"{post.get('title')} — {ctx.brand.get('brand_name')}")
                pdesc = str(meta.get("description") or post.get("excerpt") or post.get("dek") or "")[:320]
                og_img = (post.get("post_image_src") or rv.get("og_image_src") or "").strip()
                rv_post = dict(rv)
                rv_post.update(
                    {
                        "body_html": body_html,
                        "page_key": seo_key,
                        "page_title": ptitle,
                        "page_description": pdesc,
                        "page_canonical": canon,
                        "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                        "json_ld_news_article": "",
                        "json_ld_blog_post": blog_post_json_ld(
                            effective_base,
                            flat,
                            post,
                            page_ext,
                        ),
                        "breadcrumbs": [
                            {"label": "Home", "href": "index.php" if page_ext == "php" else f"index.{page_ext}"},
                            {"label": str(rv.get("blog_page_header") or "Blog"), "href": f"blog.{page_ext}"},
                            {"label": str(post.get("title") or "Post")[:72], "href": None},
                        ],
                        "og_image_src": og_img,
                        "page_og_type": "article",
                    },
                )
                html = layout_tpl.render(**rv_post)
                if noise_apply:
                    html = apply_html_noise(html, rng, noise_cfg, noise_tok)
                out_name = str(meta.get("path") or f"post-{anchor}.{page_ext}")
                (site_dir / out_name).write_text(html, encoding="utf-8")

        cs_write = ctx.content.get("case_studies")
        if "case_studies" in page_keys and isinstance(cs_write, list) and cs_write:
            env_cs = make_template_env(template_dir)
            layout_cs = env_cs.get_template("layout.html")
            body_cs = env_cs.get_template("case_study_body.html")
            rv_cs = ctx.render_vars()
            idx_h = "index.php" if page_ext == "php" else f"index.{page_ext}"
            for cs in cs_write:
                if not isinstance(cs, dict):
                    continue
                slug = str(cs.get("slug") or "").strip()
                if not slug:
                    continue
                seo_k = f"case-study-{slug}"
                meta_cs = (ctx.seo.get("pages") or {}).get(seo_k) or {}
                body_html = body_cs.render(**rv_cs, case_study=cs)
                canon = str(meta_cs.get("canonical") or f"{effective_base}/case-study-{slug}.{page_ext}")
                ptitle = str(meta_cs.get("title") or f"{cs.get('title')} — {ctx.brand.get('brand_name')}")
                pdesc = str(meta_cs.get("description") or cs.get("summary") or "")[:320]
                bc_cs: list[dict[str, str | None]] = [{"label": "Home", "href": idx_h}]
                if "case_studies" in page_keys:
                    bc_cs.append({"label": "Case studies", "href": f"case_studies.{page_ext}"})
                bc_cs.append({"label": str(cs.get("title") or "Case study")[:72], "href": None})
                rv_c = dict(rv_cs)
                rv_c.update(
                    {
                        "body_html": body_html,
                        "page_key": seo_k,
                        "page_title": ptitle,
                        "page_description": pdesc,
                        "page_canonical": canon,
                        "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                        "json_ld_news_article": "",
                        "json_ld_blog_post": "",
                        "breadcrumbs": bc_cs,
                        "page_og_type": "article",
                    },
                )
                html_c = layout_cs.render(**rv_c)
                if noise_apply:
                    html_c = apply_html_noise(html_c, rng, noise_cfg, noise_tok)
                (site_dir / str(meta_cs.get("path") or f"case-study-{slug}.{page_ext}")).write_text(html_c, encoding="utf-8")

    # Clothing: write cart/checkout/shop and product pages
    if str(ctx.content.get("vertical_id") or "") == "clothing":
        prods = ctx.content.get("products")
        if isinstance(prods, list) and prods:
            env_shop = make_template_env(template_dir)
            layout_tpl = env_shop.get_template("layout.html")
            rv = ctx.render_vars()
            # Shop page is built via normal component page (product_grid), but ensure SEO title/desc
            # Cart/checkout are standalone.
            for slug, body_tpl_name, key in [
                ("cart", "cart_body.html", "cart"),
                ("checkout", "checkout_body.html", "checkout"),
            ]:
                body_tpl = env_shop.get_template(body_tpl_name)
                meta = (ctx.seo.get("pages") or {}).get(key) or {}
                body_html = body_tpl.render(**rv)
                canon = str(meta.get("canonical") or f"{effective_base}/{slug}.{page_ext}")
                ptitle = str(meta.get("title") or f"{slug.title()} — {ctx.brand.get('brand_name')}")
                pdesc = str(meta.get("description") or "")[:320]
                rv_page = dict(rv)
                rv_page.update(
                    {
                        "body_html": body_html,
                        "page_key": key,
                        "page_title": ptitle,
                        "page_description": pdesc,
                        "page_canonical": canon,
                        "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                        "json_ld_news_article": "",
                        "json_ld_blog_post": "",
                        "breadcrumbs": [
                            {"label": "Home", "href": "index.php" if page_ext == "php" else f"index.{page_ext}"},
                            {"label": slug.title(), "href": None},
                        ],
                        "page_og_type": "website",
                    }
                )
                html = layout_tpl.render(**rv_page)
                if noise_apply:
                    html = apply_html_noise(html, rng, noise_cfg, noise_tok)
                (site_dir / f"{slug}.{page_ext}").write_text(html, encoding="utf-8")

    # Service area pages (city/district pages for local SEO)
    service_zones = ctx.brand.get("service_area_zones") or []
    vid_sa = str(ctx.content.get("vertical_id") or "").strip()
    if service_zones and vid_sa not in ("news", "clothing"):
        env_sa = make_template_env(template_dir)
        layout_tpl_sa = env_sa.get_template("layout.html")
        rv_sa = ctx.render_vars()
        flat_sa = {**ctx.brand, **ctx.content}
        brand_nm_sa = ctx.brand.get("brand_name", "Business")
        activity_sa = str(ctx.content.get("activity_summary") or "services")
        svc_items = ctx.content.get("service_items") or []
        for zone in service_zones:
            zone_slug = re.sub(r"[^a-z0-9]+", "-", zone.lower()).strip("-")
            sa_key = f"service-area-{zone_slug}"
            svc_list_html = ""
            if isinstance(svc_items, list) and svc_items:
                items_html = "".join(
                    f"<li><strong>{s.get('title', '')}</strong>: {s.get('text', '')}</li>"
                    for s in svc_items if isinstance(s, dict)
                )
                svc_list_html = f"<ul>{items_html}</ul>"
            body_content = (
                f"<section class='block'><div class='container narrow'>"
                f"<h1>{activity_sa.title()} in {zone}</h1>"
                f"<p>{brand_nm_sa} provides professional {activity_sa} throughout {zone} and surrounding areas. "
                f"Our team has been serving the {zone} community since {ctx.brand.get('founded_year', 2015)}, "
                f"delivering consistent results backed by local knowledge and responsive scheduling.</p>"
                f"<h2>Our services in {zone}</h2>"
                f"{svc_list_html}"
                f"<h2>Why choose {brand_nm_sa} in {zone}?</h2>"
                f"<p>Local presence means faster response times, familiarity with area-specific needs, "
                f"and a team that values its reputation in the community. Contact us to discuss your "
                f"requirements in {zone}.</p>"
                f"<p><a href='contact.{page_ext}' class='btn'>Get a quote for {zone}</a></p>"
                f"</div></section>"
            )
            sa_fname = f"service-area-{zone_slug}.{page_ext}"
            sa_title = f"{activity_sa.title()} in {zone} — {brand_nm_sa}"
            sa_desc = f"{brand_nm_sa} offers {activity_sa} in {zone}. Local team, responsive scheduling."
            sa_canon = f"{effective_base}/{sa_fname}"
            # Register in SEO
            ctx.seo.setdefault("pages", {})[sa_key] = {
                "title": sa_title,
                "description": sa_desc[:320],
                "path": sa_fname,
                "canonical": sa_canon,
            }
            rv_page_sa = dict(rv_sa)
            rv_page_sa.update({
                "body_html": body_content,
                "page_key": sa_key,
                "page_title": sa_title,
                "page_description": sa_desc,
                "page_canonical": sa_canon,
                "json_ld_organization": ctx.seo.get("json_ld_organization") or "",
                "json_ld_news_article": "",
                "json_ld_blog_post": "",
                "breadcrumbs": [
                    {"label": "Home", "href": "index.php" if page_ext == "php" else f"index.{page_ext}"},
                    {"label": "Service areas", "href": None},
                    {"label": zone, "href": None},
                ],
                "page_og_type": "website",
            })
            sa_html = layout_tpl_sa.render(**rv_page_sa)
            if noise_apply:
                sa_html = apply_html_noise(sa_html, rng, noise_cfg, noise_tok)
            (site_dir / sa_fname).write_text(sa_html, encoding="utf-8")

    noise_files = write_noise_assets(site_dir, rng, noise_cfg, str(ctx.content.get("vertical_id") or ""))
    ctx.noise["generated_files"] = noise_files

    # Asset integrity check: referenced gallery files must exist if using local paths.
    for p in site_dir.glob(f"*.{page_ext}"):
        html = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'\\bsrc=\"(img/gallery/[^\"]+)\"', html):
            rel = m.group(1)
            if rel and not (site_dir / rel).is_file():
                raise ValueError(f"Missing referenced gallery asset: {rel} (in {p.name})")

    env = make_template_env(template_dir)
    render_vars = ctx.render_vars()
    junk_keys = list(junk_keys_pre)
    legal_titles = {
        "privacy-policy": "Privacy Policy",
        "terms-of-service": "Terms of Service",
        "cookie-policy": "Cookie Policy",
        "refund-policy": ("Refund Policy" if vid == "clothing" else "Cancellation Policy"),
        "shipping-policy": ("Shipping Policy" if vid == "clothing" else "Service Terms"),
        "corrections-policy": "Corrections Policy",
        "ethics-policy": "Ethics Policy",
        "republishing-policy": "Republishing Policy",
        "disclaimer": "Disclaimer",
        "accessibility": "Accessibility",
    }
    legal_cfg = cfg.get("legal") if isinstance(cfg.get("legal"), dict) else {}
    legal_mode = str((legal_cfg or {}).get("mode") or "production").strip().lower()
    _gp = ctx.brand.get("geo_profile") if isinstance(ctx.brand.get("geo_profile"), dict) else {}
    _legal_lang = str(_gp.get("language") or _gp.get("legal_locale") or "en")
    brand_nm = ctx.brand.get("brand_name", "the company")
    activity = str(ctx.content.get("activity_summary") or "its services")
    ld_json = ctx.seo.get("json_ld_organization") or ""
    for junk in junk_keys:
        title = legal_titles.get(junk, junk.replace("-", " ").title())
        topic = title.lower()
        if junk in ("corrections-policy", "ethics-policy", "republishing-policy"):
            body = newsroom_policy_html(
                junk,
                str(brand_nm),
                str(ctx.brand.get("city") or ""),
                str(ctx.brand.get("country") or ""),
                mode=legal_mode,
            )
        elif junk in ("refund-policy", "shipping-policy"):
            if vid == "clothing":
                body = trust_policy_html(
                    junk,
                    str(brand_nm),
                    str(ctx.brand.get("city") or ""),
                    str(ctx.brand.get("country") or ""),
                    ctx.brand.get("founded_year"),
                    mode=legal_mode,
                )
            else:
                body = service_policy_html(
                    junk,
                    str(brand_nm),
                    activity,
                    str(ctx.brand.get("city") or ""),
                    str(ctx.brand.get("country") or ""),
                    ctx.brand.get("founded_year"),
                    mode=legal_mode,
                )
        elif junk == "disclaimer":
            body = disclaimer_page_html(str(brand_nm), activity, mode=legal_mode)
        elif junk == "accessibility":
            body = accessibility_page_html(str(brand_nm), mode=legal_mode)
        else:
            body = legal_document_html(
                str(brand_nm),
                activity,
                title,
                junk,
                mode=legal_mode,
                vertical_id=vid,
                language=_legal_lang,
            )
        jp = (ctx.seo.get("pages") or {}).get(junk) or {}
        canon = str(jp.get("canonical") or f"{effective_base}/{junk}.{page_ext}")
        ptitle = str(jp.get("title") or f"{title} — {brand_nm}")
        pdesc = str(jp.get("description") or f"How {brand_nm} describes {topic} for site visitors.")
        legal_html = render_junk_page(
            env,
            "legal_page.html",
            {
                **render_vars,
                "legal_title": title,
                "legal_body": body,
                "page_title": ptitle,
                "page_description": pdesc,
                "page_canonical": canon,
                "json_ld_organization": ld_json,
            },
        )
        if noise_apply:
            legal_html = apply_html_noise(legal_html, rng, noise_cfg, noise_tok)
        (site_dir / f"{junk}.{page_ext}").write_text(legal_html, encoding="utf-8")

    # Production realism checks: fail generation if obvious “this is generated” tells leak.
    if legal_mode == "production":
        # 1) Template / code leaks (must not ship unrendered tokens)
        leak_markers = [
            "{{",
            "{%",
            "{rng.",
            "{random.",
            "({rng.choice",
            "({random.choice",
        ]
        for p in site_dir.glob(f"*.{page_ext}"):
            txt = p.read_text(encoding="utf-8", errors="ignore")
            low = txt.lower()
            if any(m.lower() in low for m in leak_markers):
                raise ValueError(f"Production page contains unrendered tokens in {p.name}")

        forbidden = [
            "this text is generated",
            "non-binding placeholder",
            "counsel-approved",
            "replace with counsel",
            "reviewers and internal",
            "not legal advice",
            "internal draft",
            "practical draft for review",
            "this document is a practical draft",
        ]
        rx = re.compile("|".join(re.escape(x) for x in forbidden), flags=re.IGNORECASE)
        for slug in junk_keys:
            p = site_dir / f"{slug}.{page_ext}"
            if not p.is_file():
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if rx.search(txt):
                raise ValueError(f"Production legal page contains forbidden phrase in {p.name}")

    # Mojibake detection (encoding issues) – these should never ship.
    mojibake_markers = ["вЂ", "â€™", "â€”", "�"]
    for p in site_dir.glob("**/*"):
        if not p.is_file():
            continue
        # Check filenames too
        if any(m in p.name for m in mojibake_markers):
            raise ValueError(f"Detected mojibake in filename: {p.name}")
        if p.suffix.lower() in {".php", ".html", ".xml", ".txt", ".css", ".js"}:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if any(m in txt for m in mojibake_markers):
                raise ValueError(f"Detected mojibake in {p.name}")

    canon404 = f"{effective_base}/404.{page_ext}"
    not_found_html = render_junk_page(
        env,
        "404.html",
        {
            **render_vars,
            "legal_title": "Page not found",
            "legal_body": "The page you are looking for does not exist or may have moved.",
            "page_title": f"Page not found — {brand_nm}",
            "page_description": "The requested URL was not found on this site.",
            "page_canonical": canon404,
            "json_ld_organization": ld_json,
        },
    )
    if noise_apply:
        not_found_html = apply_html_noise(not_found_html, rng, noise_cfg, noise_tok)
    (site_dir / f"404.{page_ext}").write_text(not_found_html, encoding="utf-8")

    today = date.today()
    lastmod_today = today.isoformat()
    paths_lm: list[tuple[str, str]] = []

    def _offset_days(seed: int, lo: int, hi: int) -> int:
        span = max(0, hi - lo)
        if span == 0:
            return lo
        return lo + (seed % span)

    # Core pages: index/services/contact are closer to today; about/faq/policies slightly older.
    for k in page_keys:
        meta = ctx.seo["pages"][k]
        path = "/" + meta["path"]
        base_seed = abs(hash(f"{build_id}|{k}"))
        if k in ("index", "services", "contact"):
            offs = _offset_days(base_seed, 0, 7)
        elif k in ("about", "faq"):
            offs = _offset_days(base_seed, 10, 60)
        else:
            offs = _offset_days(base_seed, 5, 90)
        lm = (today if offs == 0 else today - timedelta(days=offs)).isoformat()
        paths_lm.append((path, lm))

    for junk in junk_keys:
        meta = ctx.seo["pages"][junk]
        path = "/" + meta["path"]
        base_seed = abs(hash(f"{build_id}|{junk}"))
        offs = _offset_days(base_seed, 20, 180)
        lm = (today if offs == 0 else today - timedelta(days=offs)).isoformat()
        paths_lm.append((path, lm))
    if str(ctx.content.get("vertical_id") or "") == "news" and isinstance(news_posts, list):
        for post in news_posts:
            if not isinstance(post, dict):
                continue
            an = str(post.get("anchor") or "").strip()
            if not an:
                continue
            sm_key = f"article-{an}"
            pg = (ctx.seo.get("pages") or {}).get(sm_key) or {}
            if pg.get("path"):
                paths_lm.append((f"/{pg['path']}", str(post.get("date_iso") or lastmod_today)[:10]))
        ap = (ctx.seo.get("pages") or {}).get("authors") or {}
        if ap.get("path"):
            paths_lm.append((f"/{ap['path']}", lastmod_today))
    else:
        posts = ctx.content.get("blog_posts")
        if isinstance(posts, list):
            for post in posts:
                if not isinstance(post, dict):
                    continue
                an = str(post.get("anchor") or "").strip()
                if not an:
                    continue
                sm_key = f"post-{an}"
                pg = (ctx.seo.get("pages") or {}).get(sm_key) or {}
                if pg.get("path"):
                    paths_lm.append((f"/{pg['path']}", str(post.get("date_iso") or lastmod_today)[:10]))

    # Clothing: shop/cart/checkout only (product details are on shop#p-{slug})
    if str(ctx.content.get("vertical_id") or "") == "clothing":
        prods = ctx.content.get("products")
        if isinstance(prods, list) and prods:
            for k in ("shop", "cart", "checkout"):
                pg = (ctx.seo.get("pages") or {}).get(k) or {}
                if pg.get("path"):
                    paths_lm.append((f"/{pg['path']}", lastmod_today))

    cs_sm = ctx.content.get("case_studies")
    if "case_studies" in page_keys and isinstance(cs_sm, list) and cs_sm:
        for cs in cs_sm:
            if not isinstance(cs, dict):
                continue
            slug = str(cs.get("slug") or "").strip()
            if not slug:
                continue
            sm_key = f"case-study-{slug}"
            pg = (ctx.seo.get("pages") or {}).get(sm_key) or {}
            if pg.get("path"):
                base_seed = abs(hash(f"{build_id}|cs|{slug}"))
                offs = _offset_days(base_seed, 8, 120)
                lm = (today if offs == 0 else today - timedelta(days=offs)).isoformat()
                paths_lm.append((f"/{pg['path']}", lm))

    # Service area pages in sitemap
    if service_zones and vid_sa not in ("news", "clothing"):
        for zone in service_zones:
            zone_slug = re.sub(r"[^a-z0-9]+", "-", zone.lower()).strip("-")
            sa_key = f"service-area-{zone_slug}"
            pg = (ctx.seo.get("pages") or {}).get(sa_key) or {}
            if pg.get("path"):
                base_seed = abs(hash(f"{build_id}|sa|{zone_slug}"))
                offs = _offset_days(base_seed, 5, 90)
                lm = (today if offs == 0 else today - timedelta(days=offs)).isoformat()
                paths_lm.append((f"/{pg['path']}", lm))

    seo_flags = cfg.get("seo") or {}
    if seo_flags.get("generate_sitemap", True):
        (site_dir / "sitemap.xml").write_text(
            build_sitemap_xml(effective_base, paths_lm),
            encoding="utf-8",
        )
    if seo_flags.get("generate_robots", True):
        (site_dir / "robots.txt").write_text(
            build_robots_txt(effective_base, "/sitemap.xml"),
            encoding="utf-8",
        )

    write_htaccess(site_dir)

    seed_used = cfg.get("_per_site_seed")
    manifest_payload = {
        "build_id": build_id,
        "template_id": template_id,
        "seed": seed_used,
        "brand_name": ctx.brand.get("brand_name"),
        "vertical_id": ctx.content.get("vertical_id"),
        "theme_pack_folder": ctx.meta.get("theme_pack_folder"),
        "pages": ctx.structure.get("pages"),
        "validations": ctx.structure.get("validations"),
        "noise": ctx.noise,
        "base_url": effective_base,
    }
    if bool(cfg.get("write_build_manifest")):
        write_build_manifest(site_dir, manifest_payload)
        (site_dir / ".ui-site-meta.json").unlink(missing_ok=True)
    else:
        write_ui_site_meta(site_dir, manifest_payload)

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
