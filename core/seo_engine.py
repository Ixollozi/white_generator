from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from xml.sax.saxutils import escape

def _aux_page_copy(slug: str, *, vertical_id: str | None) -> tuple[str, str]:
    """Title/description for policy pages; varies by vertical to avoid e-commerce leakage."""
    s = (slug or "").strip()
    vid = (vertical_id or "").strip()
    base: dict[str, tuple[str, str]] = {
        "privacy-policy": ("Privacy Policy", "Personal data practices, retention, and how to reach our privacy contact."),
        "terms-of-service": ("Terms of Service", "Rules for using this site, quotes, and service engagements."),
        "cookie-policy": ("Cookie Policy", "Cookies, analytics, and how to control tracking preferences."),
    }
    if s in base:
        return base[s]
    if s == "refund-policy":
        if vid == "clothing":
            return ("Refund Policy", "Returns, refunds timing, and non-refundable categories.")
        return ("Cancellation Policy", "Cancellations, rescheduling, and credits for booked services.")
    if s == "shipping-policy":
        if vid == "clothing":
            return ("Shipping Policy", "Processing windows, carriers, and delivery estimates by region.")
        return ("Service Terms", "Service delivery windows, access requirements, and scope confirmation.")
    if s == "corrections-policy":
        return ("Corrections Policy", "How we publish corrections, updates, and clarifications.")
    if s == "ethics-policy":
        return ("Ethics Policy", "Sourcing, conflicts of interest, and editorial standards.")
    if s == "republishing-policy":
        return ("Republishing Policy", "How to quote, link, or republish content with attribution.")
    return (s.replace("-", " ").title(), "Information for site visitors.")


def _schema_org_type(ctx: dict[str, Any]) -> str:
    v = str(ctx.get("vertical_id") or "").strip()
    _type_map: dict[str, str] = {
        "cleaning": "LocalBusiness",
        "fitness": "LocalBusiness",
        "clothing": "LocalBusiness",
        "cafe_restaurant": "Restaurant",
        "news": "NewsMediaOrganization",
        "dental": "Dentist",
        "medical": "MedicalBusiness",
        "plumbing": "HomeAndConstructionBusiness",
        "roofing": "HomeAndConstructionBusiness",
        "electrical": "HomeAndConstructionBusiness",
        "landscaping": "HomeAndConstructionBusiness",
        "auto_repair": "AutoRepair",
        "legal": "ProfessionalService",
        "consulting": "ProfessionalService",
        "accounting": "ProfessionalService",
        "real_estate": "RealEstateAgent",
        "moving": "LocalBusiness",
        "pest_control": "LocalBusiness",
        "marketing_agency": "ProfessionalService",
    }
    if v == "hvac":
        ident = f"{ctx.get('brand_name')}|{ctx.get('city')}|{ctx.get('domain')}"
        h = int(hashlib.sha256(ident.encode("utf-8")).hexdigest(), 16)
        return "LocalBusiness" if (h % 2 == 0) else "HomeAndConstructionBusiness"
    return _type_map.get(v, "Organization")


def _organization_ld(base: str, ctx: dict[str, Any]) -> str:
    brand = ctx.get("brand_name", "Site")
    desc = (ctx.get("seo_blurb") or ctx.get("tagline") or "")[:600]
    email = ctx.get("email") or ""
    phone = ctx.get("phone") or ""
    street = (ctx.get("address_line1") or "").strip()
    city = (ctx.get("city") or "").strip()
    region = (ctx.get("region") or "").strip()
    postal = (ctx.get("postal_code") or "").strip()
    country = (ctx.get("country") or "").strip()
    address_mode = str(ctx.get("address_mode") or "").strip().lower()
    primary_type = _schema_org_type(ctx)
    vid = str(ctx.get("vertical_id") or "").strip()
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": primary_type,
        "name": brand,
        "url": base + "/",
        "description": desc,
    }
    if vid == "hvac" and primary_type == "LocalBusiness":
        payload["additionalType"] = "https://schema.org/HomeAndConstructionBusiness"
    if email:
        payload["email"] = email
    if phone:
        payload["telephone"] = phone
    if street or city or postal or country:
        addr_obj: dict[str, Any] = {"@type": "PostalAddress"}
        # Fictional/fake: omit street in schema; catalog/hybrid/default include catalog streets.
        if street and address_mode not in {"fictional", "fake"}:
            addr_obj["streetAddress"] = street
        if city:
            addr_obj["addressLocality"] = city
        if region:
            addr_obj["addressRegion"] = region
        if postal:
            addr_obj["postalCode"] = postal
        if country:
            addr_obj["addressCountry"] = country
        payload["address"] = addr_obj
    hw = (ctx.get("hours_weekday") or "").strip()
    hd = (ctx.get("hours_display") or "").strip()
    if vid == "cafe_restaurant" and hd:
        payload["openingHours"] = hd
    elif hw:
        # Prefer structured hours for better schema validation.
        # Input expected like: "Mon–Fri 7:00–18:00 (dispatch)" or "Mon-Fri 09:00-18:00".
        parsed = _opening_hours_spec(hw)
        if parsed:
            payload["openingHoursSpecification"] = parsed
        else:
            payload["openingHours"] = hw
    fy = ctx.get("founded_year")
    if fy is not None and str(fy).strip():
        payload["foundingDate"] = str(fy)
    logo = (ctx.get("logo_src") or "").strip()
    if logo and base:
        payload["logo"] = f"{base.rstrip('/')}/{logo.lstrip('/')}"
    same: list[str] = []
    for k in ("social_twitter", "social_linkedin", "social_facebook", "social_instagram"):
        u = (ctx.get(k) or "").strip()
        if u:
            same.append(u)
    if same:
        payload["sameAs"] = same
    price_range = (ctx.get("price_range") or "").strip()
    if price_range:
        payload["priceRange"] = price_range
    # Geo coordinates
    geo_lat = ctx.get("geo_lat")
    geo_lng = ctx.get("geo_lng")
    if geo_lat is not None and geo_lng is not None:
        payload["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": str(geo_lat),
            "longitude": str(geo_lng),
        }
    # Area served (stable per-site order so batches don’t share identical JSON-LD ordering)
    service_zones = ctx.get("service_area_zones")
    if isinstance(service_zones, list) and service_zones:
        ld_seed = int(hashlib.sha256(f"{brand}|{city}|{base}".encode("utf-8")).hexdigest(), 16)
        zones_sorted = sorted(
            service_zones,
            key=lambda z: hashlib.sha256(f"{ld_seed}|{z}".encode("utf-8")).hexdigest(),
        )
        payload["areaServed"] = [{"@type": "City", "name": z} for z in zones_sorted]
    elif address_mode == "catalog" and city:
        payload["areaServed"] = {"@type": "City", "name": city}
    elif address_mode in {"fictional", "fake"}:
        area = (ctx.get("service_area") or ctx.get("city") or "").strip()
        if area:
            payload["areaServed"] = area
    # Founder
    team_items = ctx.get("team_items")
    if isinstance(team_items, list) and team_items:
        first = team_items[0]
        if isinstance(first, dict) and first.get("name"):
            payload["founder"] = {"@type": "Person", "name": first["name"]}
    # AggregateRating for local businesses with testimonials
    review_count = ctx.get("review_count")
    review_avg = ctx.get("review_avg")
    if (
        ctx.get("schema_publish_aggregate_rating", True)
        and review_count
        and review_avg
    ):
        payload["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(review_avg),
            "reviewCount": str(review_count),
            "bestRating": "5",
            "worstRating": "1",
        }
    # TikTok in sameAs
    tiktok = (ctx.get("social_tiktok") or "").strip()
    if tiktok and tiktok not in same:
        same.append(tiktok)
        payload["sameAs"] = same
    # acceptsReservations for restaurants
    if vid == "cafe_restaurant":
        payload["acceptsReservations"] = "True"
        payload["servesCuisine"] = ctx.get("cuisine_type") or "Contemporary"
        payload["@type"] = "Restaurant"
    svc_items = ctx.get("service_items")
    if (
        isinstance(svc_items, list)
        and svc_items
        and payload.get("@type") not in ("NewsMediaOrganization",)
    ):
        offers: list[dict[str, Any]] = []
        for it in svc_items[:12]:
            if isinstance(it, dict) and str(it.get("title") or "").strip():
                off: dict[str, Any] = {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": str(it["title"]).strip(),
                    },
                }
                sp = str(it.get("schema_price") or "").strip()
                sc = str(it.get("schema_price_currency") or "").strip()
                if sp and sc:
                    off["price"] = sp
                    off["priceCurrency"] = sc
                offers.append(off)
        if offers:
            payload["hasOfferCatalog"] = {
                "@type": "OfferCatalog",
                "name": f"{brand} — service catalog",
                "itemListElement": offers,
            }
    ka_generic = [
        "Local customer service",
        "Appointment scheduling",
        "Project delivery",
        "Quality standards",
    ]
    ka_by_vid: dict[str, list[str]] = {
        "cafe_restaurant": [
            "Restaurant reservations",
            "Seasonal menus",
            "Food preparation",
            "Hospitality",
        ],
        "cleaning": ["Commercial cleaning", "Floor care", "Sanitation", "Route scheduling"],
        "news": ["Editorial standards", "Fact checking", "Local reporting", "Corrections"],
        "legal": ["Legal intake", "Document review", "Risk disclosure", "Client confidentiality"],
        "accounting": ["Bookkeeping", "Tax compliance", "Payroll remittance", "Financial reporting"],
    }
    pool_ka = ka_by_vid.get(vid, ka_generic)
    h_ka = int(hashlib.sha256(f"{brand}|{city}|{base}|knowsAbout".encode("utf-8")).hexdigest(), 16)
    order_ix = sorted(
        range(len(pool_ka)),
        key=lambda i: hashlib.sha256(f"{h_ka}|{i}".encode("utf-8")).hexdigest(),
    )
    n_ka = 2 + (h_ka % 3)
    knows_list = [pool_ka[j] for j in order_ix[: min(n_ka, len(pool_ka))]]
    if knows_list:
        payload["knowsAbout"] = knows_list
    return json.dumps(payload, ensure_ascii=False)


def _opening_hours_spec(raw: str) -> list[dict[str, Any]]:
    """
    Best-effort parse for common hour strings into openingHoursSpecification.
    Returns [] when parsing fails.
    """
    s = (raw or "").strip()
    if not s:
        return []
    # Basic patterns: "Mon–Fri 7:00–18:00", "Mon-Fri 09:00-18:00"
    m = re.match(
        r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[–-](Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})",
        s,
    )
    if not m:
        return []
    day_a, day_b, opens, closes = m.group(1), m.group(2), m.group(3), m.group(4)
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    try:
        ia = order.index(day_a)
        ib = order.index(day_b)
    except ValueError:
        return []
    if ib < ia:
        return []
    days = order[ia : ib + 1]
    return [
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": [f"https://schema.org/{d}" for d in days],
            "opens": opens,
            "closes": closes,
        }
    ]


def register_auxiliary_pages_seo(
    seo: dict[str, Any],
    flat: dict[str, Any],
    extra_slugs: list[str],
    page_ext: str,
    base: str,
) -> None:
    """Sitemap/SEO entries for policy pages not in the main template manifest."""
    brand = str(flat.get("brand_name", "Site"))
    city = (flat.get("city") or "").strip()
    geo = f" ({city})" if city else ""
    base_clean = base.rstrip("/")
    pages = seo.setdefault("pages", {})
    vertical_id = str(flat.get("vertical_id") or "").strip()
    for slug in extra_slugs:
        if slug in pages:
            continue
        title_h, desc_core = _aux_page_copy(slug, vertical_id=vertical_id)
        fname = f"{slug}.{page_ext}"
        pages[slug] = {
            "title": f"{title_h} — {brand}",
            "description": f"{desc_core}{geo} — {brand}.",
            "path": fname,
            "canonical": f"{base_clean}/{fname}",
        }


def apply_seo(
    ctx: dict[str, Any],
    pages: list[str],
    page_extension: str,
    base_url: str = "https://example.com",
) -> dict[str, Any]:
    """Populate ctx['seo'] with per-page title/description, canonical URLs, and JSON-LD."""
    base = str(base_url or "https://example.com").rstrip("/")
    brand = ctx.get("brand_name", "Site")
    tagline = ctx.get("tagline", "")
    seo_blurb = (ctx.get("seo_blurb") or "").strip()
    seo_pages: dict[str, dict[str, str]] = {}
    urls: list[str] = []

    index_description = seo_blurb if seo_blurb else tagline
    city = (ctx.get("city") or "").strip()
    vlab = (ctx.get("vertical_seo_label") or "").strip()

    def _idx_title() -> str:
        parts = [brand]
        if vlab:
            parts.append(vlab)
        if city:
            parts.append(city)
        return brand if len(parts) == 1 else " — ".join(parts)

    svc_head = str(ctx.get("services_heading") or "Services")
    services_desc = (ctx.get("services_seo_description") or "").strip()
    if not services_desc:
        sintro = (ctx.get("services_intro") or "").strip()
        services_desc = (sintro[:220] + "…") if len(sintro) > 220 else sintro
        if not services_desc:
            services_desc = index_description

    blog_intro = (ctx.get("blog_intro") or "").strip() or index_description
    faq_intro = (ctx.get("faq_page_intro") or "").strip() or f"Answers to common questions about {brand}."
    posts = ctx.get("blog_posts")
    first_post = posts[0] if isinstance(posts, list) and posts and isinstance(posts[0], dict) else {}
    first_title = str(first_post.get("title") or "").strip()
    blog_desc = blog_intro
    if first_title:
        blog_desc = f"{blog_intro} Featured: {first_title}."[:320]

    vid = str(ctx.get("vertical_id") or "").strip()
    if vid == "news":
        blog_desc = (
            f"{blog_intro} Categories, explainers, and sourced reporting from {brand}"
            f"{f' ({city})' if city else ''}."
        )[:320]
        if first_title:
            blog_desc = (
                f"{blog_intro} Recent: {first_title}. "
                f"Browse by category, byline, and date — {brand}."
            )[:320]

    # Vary separator for title uniqueness
    import hashlib as _hl
    _sep_seed = int(_hl.sha256(f"sep|{brand}".encode()).hexdigest(), 16)
    _seps = (" — ", " | ", " - ", " : ")
    sep = _seps[_sep_seed % len(_seps)]
    _brand_first = (_sep_seed >> 4) % 3 == 0

    def _title(label: str, loc: str = "") -> str:
        parts = [label]
        if loc:
            parts.append(loc)
        parts.append(brand)
        if _brand_first:
            parts = [brand] + [p for p in parts if p != brand]
        return sep.join(parts)

    blog_label = str(ctx.get("blog_page_header") or "Blog")
    res_head = str(ctx.get("resources_page_header") or "Resources")
    blog_title_val = _title(blog_label, city)
    if vid == "news":
        blog_title_val = f"{blog_label} | Latest reporting{f' — {city}' if city else ''} | {brand}"
    ind_page_head = str(ctx.get("industries_page_header") or "Industries we serve").strip() or "Industries we serve"
    titles = {
        "index": _idx_title(),
        "about": _title("About", city),
        "contact": _title("Contact", city),
        "services": _title(svc_head, city),
        "blog": blog_title_val,
        "faq": _title("FAQ", city),
        "team": _title("Our Team", city),
        "testimonials": _title("Testimonials", city),
        "pricing": _title("Pricing", city),
        "process": _title("Our Process", city),
        "portfolio": _title("Portfolio", city),
        "case_studies": _title("Case studies", city),
        "careers": _title("Careers", city),
        "industries": _title(ind_page_head, city),
        "resources": _title(res_head, city),
        "service_areas": _title("Service areas", city),
    }
    descriptions = {
        "index": index_description,
        "about": (
            f"{brand} — background, team, and how we work in {city}."
            if city
            else f"Learn more about {brand}: background, values, and team."
        ),
        "contact": (
            f"Phone, email, hours, and map for {brand} in {city}. Use the contact form or reach out directly."
            if city
            else f"Reach {brand} by phone, email, or the contact form."
        ),
        "services": services_desc,
        "blog": blog_desc[:320] if len(blog_desc) > 320 else blog_desc,
        "faq": (
            f"{faq_intro[:200]} Covers hours, location{f' ({city})' if city else ''}, bookings, and policies."
            if city
            else faq_intro[:320]
        ),
        "team": f"Meet the {brand} team{f' in {city}' if city else ''}. Background, roles, and how to reach us.",
        "testimonials": f"What clients say about {brand}{f' in {city}' if city else ''}. Real reviews and feedback.",
        "pricing": f"Pricing and service options from {brand}{f' in {city}' if city else ''}. Transparent rates.",
        "process": f"How {brand} works{f' in {city}' if city else ''}. Our step-by-step process from first contact to delivery.",
        "portfolio": f"Selected work and project highlights from {brand}{f' serving {city}' if city else ''}.",
        "case_studies": f"Client outcomes, challenges, and solutions documented by {brand}{f' in {city}' if city else ''}.",
        "careers": f"Open roles and how we hire at {brand}{f' ({city})' if city else ''}.",
        "industries": (
            (str(ctx.get("industries_page_intro") or "").strip()[:320] or None)
            or f"Sectors and client types {brand} supports{f' around {city}' if city else ''}."
        ),
        "resources": f"Guides, downloads, and helpful links from {brand}.",
        "service_areas": f"Neighborhoods and districts {brand} serves{f' near {city}' if city else ''}.",
    }

    def _trim_desc(text: str, key: str) -> str:
        t = (text or "").strip()
        if not t:
            return t
        h = int(_hl.sha256(f"desc|{brand}|{key}".encode()).hexdigest(), 16)
        lo, hi = 118, 158
        span = hi - lo
        cap = lo + (h % (span + 1))
        if len(t) <= cap:
            return t
        return (t[: max(80, cap - 1)].rsplit(" ", 1)[0] + "…") if len(t) > cap else t[:cap]

    _prof_industries_file = frozenset({"legal", "consulting", "medical", "dental", "accounting"})

    for key in pages:
        if key == "index":
            fname = f"index.{page_extension}"
        elif key == "industries" and vid in _prof_industries_file:
            fname = f"practice-areas.{page_extension}"
        else:
            fname = f"{key}.{page_extension}"
        urls.append(f"/{fname}")
        title = titles.get(key, f"{key.replace('_', ' ').title()} — {brand}")
        desc = _trim_desc(str(descriptions.get(key, tagline)), key)
        path_url = f"/{fname}"
        seo_pages[key] = {
            "title": title,
            "description": desc,
            "path": fname,
            "canonical": base + path_url,
        }

    return {
        "pages": seo_pages,
        "urls": urls,
        "json_ld_organization": _organization_ld(base, ctx),
    }


def build_sitemap_xml(base_url: str, paths_with_lastmod: list[tuple[str, str]]) -> str:
    base = base_url.rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, lastmod in paths_with_lastmod:
        loc = escape(f"{base}{path}")
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def build_robots_txt(base_url: str, sitemap_path: str = "/sitemap.xml") -> str:
    base = base_url.rstrip("/")
    sm = f"{base}{sitemap_path}" if sitemap_path.startswith("/") else f"{base}/{sitemap_path}"
    return f"User-agent: *\nAllow: /\n\nSitemap: {sm}\n"


def news_article_json_ld(base: str, flat: dict[str, Any], post: dict[str, Any], page_ext: str) -> str:
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Site"))
    anchor = str(post.get("anchor") or "").strip()
    fname = f"article-{anchor}.{page_ext}"
    page_url = f"{base_clean}/{fname}"
    img = (post.get("post_image_src") or flat.get("og_image_src") or "").strip()
    if img and not img.startswith("http"):
        img = f"{base_clean}/{img.lstrip('/')}"
    logo = (flat.get("logo_src") or "").strip()
    logo_url = f"{base_clean}/{logo.lstrip('/')}" if logo else ""
    publisher: dict[str, Any] = {
        "@type": "NewsMediaOrganization",
        "name": brand,
    }
    if logo_url:
        publisher["logo"] = {"@type": "ImageObject", "url": logo_url}
    an = str(post.get("author_name") or "").strip()
    author_ld: dict[str, Any] = {"@type": "Person", "name": an or brand}
    if an:
        author_ld["url"] = f"{page_url}#author"
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": post.get("title"),
        "description": (str(post.get("excerpt") or post.get("dek") or ""))[:500],
        "datePublished": post.get("date_iso"),
        "dateModified": post.get("date_iso"),
        "author": author_ld,
        "publisher": publisher,
        "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
    }
    if img:
        payload["image"] = [img]
    cat = str(post.get("category") or "").strip()
    if cat:
        payload["articleSection"] = cat
    tags = post.get("tags")
    if isinstance(tags, list) and tags:
        payload["keywords"] = ", ".join(str(t) for t in tags if t)[:280]
    alt = str(post.get("image_alt") or "").strip()
    if alt:
        base_kw = str(payload.get("keywords") or "").strip()
        extra = f"{base_kw}, image: {alt[:160]}" if base_kw else f"image: {alt[:200]}"
        payload["keywords"] = extra[:280]
    rm = post.get("read_minutes")
    try:
        rm_i = int(rm)  # type: ignore[arg-type]
        if rm_i > 0:
            payload["timeRequired"] = f"PT{rm_i}M"
    except (TypeError, ValueError):
        pass
    gp = flat.get("geo_profile")
    gl = str(
        flat.get("locale") or (gp.get("language") if isinstance(gp, dict) else "") or "en"
    ).strip()[:12]
    if gl:
        payload["inLanguage"] = gl
    return json.dumps(payload, ensure_ascii=False)


def blog_post_json_ld(base: str, flat: dict[str, Any], post: dict[str, Any], page_ext: str) -> str:
    """Schema.org BlogPosting for non-news long-form posts."""
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Site"))
    anchor = str(post.get("anchor") or "").strip()
    fname = f"post-{anchor}.{page_ext}"
    page_url = f"{base_clean}/{fname}"
    img = (post.get("post_image_src") or flat.get("og_image_src") or "").strip()
    if img and not img.startswith("http"):
        img = f"{base_clean}/{img.lstrip('/')}"
    logo = (flat.get("logo_src") or "").strip()
    logo_url = f"{base_clean}/{logo.lstrip('/')}" if logo else ""
    publisher: dict[str, Any] = {"@type": "Organization", "name": brand}
    if logo_url:
        publisher["logo"] = {"@type": "ImageObject", "url": logo_url}
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.get("title"),
        "description": (str(post.get("excerpt") or post.get("dek") or ""))[:500],
        "datePublished": post.get("date_iso"),
        "dateModified": post.get("date_iso"),
        "author": {"@type": "Person", "name": (post.get("author_name") or brand)},
        "publisher": publisher,
        "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
    }
    if img:
        payload["image"] = [img]
    return json.dumps(payload, ensure_ascii=False)


def register_case_study_pages(
    seo: dict[str, Any],
    flat: dict[str, Any],
    case_studies: list[dict[str, Any]],
    page_ext: str,
    base: str,
) -> None:
    pages = seo.setdefault("pages", {})
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Site"))
    city = (flat.get("city") or "").strip()
    geo = f" — {city}" if city else ""
    for cs in case_studies:
        if not isinstance(cs, dict):
            continue
        slug = str(cs.get("slug") or "").strip()
        if not slug:
            continue
        fname = f"case-study-{slug}.{page_ext}"
        title = str(cs.get("title") or "Case study")
        desc = str(cs.get("summary") or "")[:320]
        pages[f"case-study-{slug}"] = {
            "title": f"{title}{geo} — {brand}",
            "description": desc or f"How {brand} delivered results for a local client.",
            "path": fname,
            "canonical": f"{base_clean}/{fname}",
        }


def register_blog_extra_pages(
    seo: dict[str, Any],
    flat: dict[str, Any],
    posts: list[dict[str, Any]],
    page_ext: str,
    base: str,
) -> None:
    """Sitemap/SEO paths for long-form blog posts (non-news verticals)."""
    pages = seo.setdefault("pages", {})
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Site"))
    for post in posts:
        if not isinstance(post, dict):
            continue
        anchor = str(post.get("anchor") or "").strip()
        if not anchor:
            continue
        fname = f"post-{anchor}.{page_ext}"
        title = str(post.get("title") or "Post")
        desc = str(post.get("excerpt") or post.get("dek") or "")[:320]
        pages[f"post-{anchor}"] = {
            "title": f"{title} — {brand}",
            "description": desc,
            "path": fname,
            "canonical": f"{base_clean}/{fname}",
        }


def register_news_extra_pages(
    seo: dict[str, Any],
    flat: dict[str, Any],
    posts: list[dict[str, Any]],
    page_ext: str,
    base: str,
) -> None:
    """Sitemap/SEO paths for long-form articles + authors index (news vertical)."""
    pages = seo.setdefault("pages", {})
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Site"))
    city = (flat.get("city") or "").strip()
    geo = f" — {city}" if city else ""
    for post in posts:
        if not isinstance(post, dict):
            continue
        anchor = str(post.get("anchor") or "").strip()
        if not anchor:
            continue
        fname = f"article-{anchor}.{page_ext}"
        title = str(post.get("title") or "Article")
        desc = str(post.get("excerpt") or post.get("dek") or "")[:280]
        cat = str(post.get("category") or "").strip()
        kind = str(post.get("article_kind") or "").strip()
        tag_line = ""
        tags = post.get("tags")
        if isinstance(tags, list) and tags:
            tag_line = ", ".join(str(x) for x in tags[:4] if x)
        og_bits = [desc]
        if tag_line:
            og_bits.append(f"Tags: {tag_line}.")
        if post.get("read_minutes"):
            og_bits.append(f"About {post.get('read_minutes')} min read.")
        long_desc = " ".join(og_bits)[:320]
        kind_bit = f" ({kind})" if kind else ""
        cat_bit = f" — {cat}" if cat else ""
        pages[f"article-{anchor}"] = {
            "title": f"{title}{cat_bit}{kind_bit} — {brand}",
            "description": long_desc or desc,
            "path": fname,
            "canonical": f"{base_clean}/{fname}",
        }
    afname = f"authors.{page_ext}"
    pages["authors"] = {
        "title": f"Newsroom staff & bylines — {brand}{geo}",
        "description": (
            f"Reporters and editors behind {brand}{geo}: bios, beats, and how to reach the desk."
        )[:320],
        "path": afname,
        "canonical": f"{base_clean}/{afname}",
    }


def register_product_pages(
    seo: dict[str, Any],
    flat: dict[str, Any],
    page_ext: str,
    base: str,
) -> None:
    """Sitemap/SEO entries for clothing catalog (shop/cart/checkout; catalog lives on shop)."""
    pages = seo.setdefault("pages", {})
    base_clean = base.rstrip("/")
    brand = str(flat.get("brand_name", "Shop"))
    # Top-level shop flow pages (product copy is embedded on shop with #p-{slug} anchors)
    for slug, title_h, desc in [
        (
            "shop",
            "Shop",
            "Full catalog on one page: fabric notes, measured sizing, and care — link to any item via in-page anchors.",
        ),
        ("cart", "Cart", "Review your items, quantities, and totals before checkout."),
        ("checkout", "Checkout", "Send a lightweight checkout request and receive confirmation by email."),
    ]:
        fname = f"{slug}.{page_ext}"
        pages[slug] = {
            "title": f"{title_h} — {brand}",
            "description": f"{desc} — {brand}.",
            "path": fname,
            "canonical": f"{base_clean}/{fname}",
        }
