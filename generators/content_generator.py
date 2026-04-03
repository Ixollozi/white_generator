from __future__ import annotations

import copy
import hashlib
import random
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml

from core.content_dates import as_of_year, founded_year_int, past_dates_recent, past_dates_spread
from core.prose_vary import (
    apply_blog_post_depth_pass,
    apply_conversational_leadin,
    apply_inject_to_random_html_paragraphs,
    apply_micro_imperfections,
    dedupe_paragraph_openers,
    inject_local_detail,
    massage_first_html_paragraph,
    pick_register,
    pick_register_for_blog_post,
    prose_chatty_strength,
    prose_humanize_enabled,
    prose_micro_imperfections_enabled,
    rewrite_if_stale_opener,
    season_phrase,
    vary_first_section_plain_shape,
    vary_paragraph_shape,
)
from core.money_locale import localize_money_labels
from core.person_names import pick_full_name, pick_signature_name, site_key_from_brand
from core.price_schema import derive_price_range_and_enrich_offers
from core.theme_pack import merge_content_overlay
from generators.newsroom_articles import enrich_news_vertical_content

# Trades / field-service niches (used by blog titles, testimonials, careers, etc.)
_TRADES_VERTICALS: frozenset[str] = frozenset(
    {"hvac", "plumbing", "electrical", "roofing", "landscaping", "pest_control", "auto_repair", "moving"},
)
# Blog slugs: avoid noisy geo tails + duplicate tokens for professional / clinical sites.
# Field-service vertical where post-type slug fragments read as fake “tags” (readiness, workflow, …).
_SLUG_TITLE_ONLY_FIELD_VERTICALS: frozenset[str] = frozenset({"pest_control"})

_PROF_BLOG_SLUG_VERTICALS: frozenset[str] = frozenset(
    {"accounting", "legal", "consulting", "medical", "dental"},
)
# Office/professional sites: no service-area spam, portfolio as matters, aligned case copy.
_PROF_OFFICE_VERTICALS: frozenset[str] = frozenset(
    {"legal", "consulting", "medical", "dental", "accounting"},
)


def _truncate_words_phrase(text: str, max_words: int) -> str:
    words = re.split(r"\s+", (text or "").strip())
    if len(words) <= max_words:
        return " ".join(words).rstrip(",;:")
    return " ".join(words[:max_words]).rstrip(",;:")


def _blog_topic_for_templates(title: str, *, activity: str = "") -> str:
    """
    Short lower-case phrase for blog templates (ledes, headings, fillers).
    Avoids jamming full titles like 'a plain-language guide to the hard part' into
    'What {brand} does for {tlow} in {city}' (ungrammatical, obviously templated).
    """
    act = (activity or "").strip().lower()
    raw = (title or "").strip()
    if not raw:
        return act or "this topic"
    tl = raw.lower().strip().rstrip(".!?…")
    needles = (
        "plain-language guide to ",
        "plain language guide to ",
        "a practical guide to ",
        "a quick guide to ",
        "beginner's guide to ",
        "beginners guide to ",
        "guide to ",
        "introduction to ",
        "an introduction to ",
        "notes on ",
        "checklist for ",
        "everything you need to know about ",
        "what you need to know about ",
    )
    for needle in needles:
        if needle in tl:
            frag = tl.split(needle, 1)[1].strip().rstrip(".!?…")
            if frag and len(frag) <= 96:
                return frag
    # Titles that already read as clauses: keep bounded length
    if re.match(r"^(how|what|why|when|where|which|our)\s", tl):
        return _truncate_words_phrase(tl, 14)
    return _truncate_words_phrase(tl, 12) if len(tl.split()) > 12 else tl or (act or "this topic")


SOURCES_BY_VERTICAL: dict[str, list[dict[str, str]]] = {
    # Fashion / apparel retail.
    "clothing": [
        {"title": "Vogue — Fashion", "url": "https://www.vogue.com/fashion", "org": "Vogue"},
        {"title": "Vogue Business", "url": "https://www.voguebusiness.com/", "org": "Vogue Business"},
        {"title": "Good On You — Guides", "url": "https://goodonyou.eco/category/guides/", "org": "Good On You"},
        {"title": "Fashion Revolution — Learn", "url": "https://www.fashionrevolution.org/learn/", "org": "Fashion Revolution"},
        {"title": "CFDA — Resources", "url": "https://cfda.com/resources", "org": "CFDA"},
        {"title": "The Business of Fashion — Topics", "url": "https://www.businessoffashion.com/topics/", "org": "The Business of Fashion"},
        {"title": "Textile Exchange — Resources", "url": "https://textileexchange.org/resources/", "org": "Textile Exchange"},
    ],
    # Restaurants / food.
    "cafe_restaurant": [
        {"title": "Eater — Neighborhood Dining", "url": "https://www.eater.com/neighborhood", "org": "Eater"},
        {"title": "Eater — Guides", "url": "https://www.eater.com/guides", "org": "Eater"},
        {"title": "OpenTable — Restaurant Stories", "url": "https://restaurant.opentable.com/news/", "org": "OpenTable"},
        {"title": "OpenTable — Hospitality Tips", "url": "https://restaurant.opentable.com/resources/", "org": "OpenTable"},
        {"title": "Zagat Stories", "url": "https://www.zagat.com/news", "org": "Zagat"},
    ],
    "cleaning": [
        {"title": "CDC — Cleaning and disinfecting", "url": "https://www.cdc.gov/hygiene/cleaning/index.html", "org": "CDC"},
        {"title": "OSHA — Safety and health topics", "url": "https://www.osha.gov/safety-and-health-topics", "org": "OSHA"},
        {"title": "EPA — Safer Choice", "url": "https://www.epa.gov/saferchoice", "org": "US EPA"},
    ],
    # News can цитировать крупные институты.
    "news": [
        {"title": "Reuters — World", "url": "https://www.reuters.com/world/", "org": "Reuters"},
        {"title": "Reuters — Business", "url": "https://www.reuters.com/business/", "org": "Reuters"},
        {"title": "World Bank — Research", "url": "https://www.worldbank.org/en/research", "org": "World Bank"},
        {"title": "OECD — Publications", "url": "https://www.oecd.org/publications/", "org": "OECD"},
        {"title": "UN News", "url": "https://news.un.org/en", "org": "United Nations"},
    ],
    # Default pool for other verticals: general, non-weird sources.
    "default": [
        {"title": "Harvard Business Review — Topics", "url": "https://hbr.org/topics", "org": "Harvard Business Review"},
        {"title": "Nielsen Norman Group — Articles", "url": "https://www.nngroup.com/articles/", "org": "NN/g"},
        {"title": "US Small Business Administration — Learning Center", "url": "https://www.sba.gov/business-guide", "org": "SBA"},
        {"title": "ISO — Standards", "url": "https://www.iso.org/standards.html", "org": "ISO"},
    ],
    "accounting": [
        {
            "title": "CRA — Businesses and self-employed",
            "url": "https://www.canada.ca/en/revenue-agency/services/tax/businesses.html",
            "org": "Canada Revenue Agency",
        },
        {
            "title": "CRA — Payroll",
            "url": "https://www.canada.ca/en/revenue-agency/services/payroll.html",
            "org": "Canada Revenue Agency",
        },
        {
            "title": "Alberta — Taxes and levies",
            "url": "https://www.alberta.ca/taxes-levies",
            "org": "Government of Alberta",
        },
        {
            "title": "CPA Canada — Business resources",
            "url": "https://www.cpacanada.ca/business-resources",
            "org": "CPA Canada",
        },
    ],
    "legal": [
        {
            "title": "Department of Justice Canada",
            "url": "https://www.justice.gc.ca/eng/",
            "org": "Department of Justice Canada",
        },
        {
            "title": "Canadian Bar Association — Public resources",
            "url": "https://www.cba.org/Publications-Resources/Publications-Media",
            "org": "Canadian Bar Association",
        },
        {
            "title": "Law Society of Alberta — For the public",
            "url": "https://www.lawsociety.ab.ca/public/",
            "org": "Law Society of Alberta",
        },
        {
            "title": "Courts of Alberta",
            "url": "https://www.albertacourts.ca/",
            "org": "Alberta Courts",
        },
    ],
}

# Country-level overrides for sources (applied on top of vertical sources).
SOURCES_BY_COUNTRY: dict[str, dict[str, list[dict[str, str]]]] = {
    "Singapore": {
        "cleaning": [
            {
                "title": "NEA Singapore — Cleaning and maintenance",
                "url": "https://www.nea.gov.sg/our-services/public-cleanliness/cleaning-and-maintenance",
                "org": "NEA Singapore",
            },
            {
                "title": "WSH Council — BizSAFE",
                "url": "https://www.tal.sg/wshc/programmes/bizsafe",
                "org": "WSH Council (BizSAFE)",
            },
            {
                "title": "Enterprise Singapore — Standards and accreditation",
                "url": "https://www.enterprisesg.gov.sg/standards-and-accreditation",
                "org": "Enterprise Singapore",
            },
        ]
    }
}


def _a(url: str, text: str) -> str:
    safe_u = escape(url, {"\"": "&quot;"})
    return (
        f'<a href="{safe_u}" rel="nofollow noopener noreferrer" target="_blank">{escape(text)}</a>'
    )


def _pick_sources(rng: random.Random, vertical_id: str, k: int = 4) -> list[dict[str, str]]:
    vid = (vertical_id or "").strip()
    src_vid = "legal" if vid == "consulting" else vid
    pool = list(SOURCES_BY_VERTICAL.get(src_vid) or SOURCES_BY_VERTICAL["default"])
    rng.shuffle(pool)
    return [dict(x) for x in pool[: max(2, min(k, len(pool)))]]


def _pick_sources_for_post(
    rng: random.Random,
    vertical_id: str,
    country: str,
    k: int = 4,
) -> list[dict[str, str]]:
    vid = (vertical_id or "").strip()
    src_vid = "legal" if vid == "consulting" else vid
    c = (country or "").strip()
    base = list(SOURCES_BY_VERTICAL.get(src_vid) or SOURCES_BY_VERTICAL["default"])
    override = list((SOURCES_BY_COUNTRY.get(c) or {}).get(src_vid) or [])
    pool = override + base
    # Dedup by URL, keep override-first.
    seen: set[str] = set()
    dedup: list[dict[str, str]] = []
    for s in pool:
        u = str(s.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        dedup.append(dict(s))
    rng.shuffle(dedup)
    return dedup[: max(2, min(k, len(dedup)))]


def _sections_visible_text(sections: list[dict[str, Any]]) -> str:
    """Rough plain text from article_sections_html."""
    parts: list[str] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        paras = sec.get("paragraphs_html") or []
        if not isinstance(paras, list):
            continue
        for ph in paras:
            if not isinstance(ph, str):
                continue
            txt = ph.replace("<", " ").replace(">", " ")
            parts.append(txt)
    return " ".join(parts)


def _ngrams(words: list[str], n: int = 3) -> set[str]:
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _similarity_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / float(len(a | b))


def _post_fingerprint(post: dict[str, Any]) -> set[str]:
    secs = post.get("article_sections_html") or []
    text = _sections_visible_text(secs)
    words = [w.lower() for w in text.split() if w.strip()]
    return _ngrams(words, 3)


def _max_similarity(fp: set[str], prev_fps: list[set[str]]) -> float:
    if not fp or not prev_fps:
        return 0.0
    best = 0.0
    for p in prev_fps:
        best = max(best, _similarity_jaccard(fp, p))
    return best


def _dedup_posts_by_anchor(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in posts:
        if not isinstance(p, dict):
            continue
        a = str(p.get("anchor") or "").strip()
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(p)
    return out


def _dedup_paragraphs_html(paragraphs_html: list[str]) -> list[str]:
    """Deduplicate paragraphs by normalized visible text (keeps first occurrence)."""
    out: list[str] = []
    seen: set[str] = set()
    for ph in paragraphs_html:
        if not isinstance(ph, str):
            continue
        key = (
            ph.replace("\u00a0", " ")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " ")
            .strip()
            .lower()
        )
        key = " ".join(key.split())
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(ph)
    return out


def _dedup_sections_html(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate paragraphs inside each section (and prune empty)."""
    out: list[dict[str, Any]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        paras = sec.get("paragraphs_html") or []
        if isinstance(paras, list):
            sec["paragraphs_html"] = _dedup_paragraphs_html([p for p in paras if isinstance(p, str)])
        if sec.get("heading") or sec.get("paragraphs_html"):
            out.append(sec)
    return out


def _strip_meta_prefix_for_slug(title: str) -> str:
    """Remove generator-style lead-ins so slugs are not dominated by blueprint-/case-snapshot- style tokens."""
    s = (title or "").strip()
    if not s:
        return s
    cut = True
    while cut:
        cut = False
        low = s.lower()
        for p in (
            "blueprint:",
            "case snapshot:",
            "field notes:",
            "field note:",
            "signals on ",
            "reference:",
            "readiness for ",
            "quick prep:",
            "compared:",
            "three paths on ",
            "internal note:",
            "update:",
            "dispatch:",
        ):
            if low.startswith(p):
                s = s[len(p) :].strip()
                cut = True
                break
    return s


_SLUG_INCOMPLETE_FINAL: frozenset[str] = frozenset(
    {
        "before",
        "after",
        "when",
        "while",
        "if",
        "on",
        "to",
        "for",
        "at",
        "by",
        "as",
        "so",
        "or",
        "and",
        "the",
        "a",
        "an",
        "we",
        "our",
        "in",
    },
)


def _strip_trailing_parenthetical_title(title: str) -> str:
    """Drop a trailing 'Title (qualifier)' for cleaner URLs while keeping display title unchanged."""
    s = (title or "").strip()
    if not s.endswith(")") or "(" not in s:
        return s
    depth = 0
    start = -1
    for j in range(len(s) - 1, -1, -1):
        ch = s[j]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                start = j
                break
    if start <= 0:
        return s
    if s[start - 1] not in " \t":
        return s
    return s[: start - 1].strip() or s


def _short_hash_token(key: str, *, n: int = 7) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:n]


_TITLE_PREFIX_BY_POST_TYPE: dict[str, list[str]] = {
    "case_study": ["Case snapshot: {t}", "Field notes: {t}", "What shifted: {t}", "Lesson from: {t}", "On the ground: {t}"],
    "comparison": ["Compared: {t}", "Three paths on {t}", "Options around {t}", "Side by side: {t}"],
    "how_to": ["Walkthrough: {t}", "Sequence for {t}", "Breaking down {t}", "Start here: {t}", "On {t}, step one"],
    "checklist": ["Checklist: {t}", "Before you start: {t}", "Readiness for {t}", "Quick prep: {t}"],
    "mistakes": ["Common missteps on {t}", "Where {t} breaks down", "Pitfalls in {t}", "Watch for: {t}"],
    "tips": ["Practical tips: {t}", "Short notes on {t}", "Fine print on {t}", "Tiny fixes: {t}"],
    "interview": ["On the record: {t}", "Conversation: {t}", "Inside view: {t}", "Q&A on {t}"],
    "company_news": ["Update: {t}", "Internal note: {t}", "This month: {t}", "Dispatch: {t}"],
    "industry_update": ["Signals on {t}", "Market note: {t}", "Watching: {t}", "Why {t} matters now", "Quick read: {t}"],
    "guide": ["Reference: {t}", "Foundations of {t}", "Plain guide: {t}", "Overview: {t}"],
}


_SLUG_FRAGMENTS_BY_POST_TYPE: dict[str, list[str]] = {
    "how_to": ["workflow", "walkthrough", "sequence", "handbook", "basics"],
    "case_study": ["outcomes", "constraints", "retrofit", "delivery-story"],
    "comparison": ["tradeoffs", "options", "side-by-side", "criteria"],
    "company_news": ["dispatch", "internal", "rollout", "update"],
    "guide": ["walkthrough", "manual", "reference", "overview"],
    "checklist": ["prep", "readiness", "audit", "verification"],
    "interview": ["conversation", "q-and-a", "backstage", "studio"],
    "industry_update": ["signals", "landscape", "pulse", "outlook"],
    "mistakes": ["pitfalls", "lessons", "risks", "watchouts"],
    "tips": ["shortcuts", "practice", "habits", "fine-print"],
}


def _trim_slug_at_word_boundary(s: str, max_len: int) -> str:
    """Avoid mid-word chops like …-bluepri (truncate at last hyphen before limit)."""
    s = (s or "").strip("-")
    if not s:
        return "post"
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    if cut.endswith("-"):
        t = cut[:-1].strip("-")
        return t or "post"
    last = cut.rfind("-")
    min_keep = max(14, max_len // 3)
    if last >= min_keep:
        return cut[:last].strip("-") or cut.strip("-")
    return cut.strip("-") or "post"


def _dedupe_adjacent_slug_parts(slug: str) -> str:
    parts = [p for p in (slug or "").strip("-").split("-") if p]
    out: list[str] = []
    for p in parts:
        if not out or out[-1] != p:
            out.append(p)
    return "-".join(out)


_SLUG_BAD_TAIL_TOKENS: frozenset[str] = frozenset(
    {
        "constraints",
        "signals",
        "quietly",
        "internal",
        "dispatch",
        "the",
        "a",
        "an",
        "we",
        "our",
        "from",
        "keeping",
        "prep",
        "update",
        "shortcuts",
        "retrofit",
        "walkthrough",
        "landscape",
        "studio",
        "habits",
        "criteria",
        "pulse",
        "rollout",
        "risks",
        "note",
        "outlook",
        "watchouts",
        "without",
        "or",
        "readiness",
        "pitfalls",
        "options",
        "workflow",
        "matters",
        "now",
        "park",
        "outlook",
        "sequence",
        "skip",
    },
)


def _slug_tail_cleanup(s: str) -> str:
    parts = [p for p in (s or "").strip("-").split("-") if p]
    while len(parts) > 2 and parts[-1] in _SLUG_BAD_TAIL_TOKENS:
        parts.pop()
    while len(parts) > 1 and parts[-1] in _SLUG_INCOMPLETE_FINAL:
        parts.pop()
    out = "-".join(parts).strip("-")
    return out if out else "post"


def _title_prefix_candidates(post_type: str, vid: str) -> list[str]:
    raw = list(_TITLE_PREFIX_BY_POST_TYPE.get(post_type) or [])
    v = (vid or "").strip()
    if v in _TRADES_VERTICALS or v == "pest_control":
        bad = (
            "blueprint",
            "case snapshot",
            "field notes",
            "field note",
            "signals on",
            "internal note",
            "dispatch:",
            "walkthrough:",
            "sequence for",
            "three paths on",
            "compared:",
        )
        raw = [x for x in raw if not any(b in x.lower() for b in bad)]
        if not raw:
            raw = ["Notes: {t}", "On {t}", "Practical view: {t}"]
    return raw


def _blog_post_slug_parts(
    title: str,
    *,
    rng: random.Random,
    city: str,
    district: str,
    post_type: str,
    vertical_id: str = "",
    site_identity: str = "",
) -> str:
    vid = (vertical_id or "").strip()
    title_only = vid in _PROF_BLOG_SLUG_VERTICALS or vid in _SLUG_TITLE_ONLY_FIELD_VERTICALS
    base_title = _strip_trailing_parenthetical_title(_strip_meta_prefix_for_slug(title))
    # Professional / selected field-service sites: slug from title only — no synthetic post-type fragments in the URL.
    if title_only:
        anchor = _slugify_ascii(base_title, max_len=88).strip("-") or "insight"
        anchor = anchor.replace("how-to", "steps").replace("how_to", "steps")
        anchor = re.sub(r"-{2,}", "-", anchor).strip("-") or "insight"
        anchor = _dedupe_adjacent_slug_parts(anchor)
        anchor = _trim_slug_at_word_boundary(anchor, 82)
        anchor = _slug_tail_cleanup(anchor)
        if vid == "pest_control" and site_identity:
            suf = hashlib.sha256(f"anchor|{site_identity}|{anchor}|{title}".encode()).hexdigest()[:5]
            anchor = f"{anchor}-{suf}"
        return anchor
    # Non-professional: title slug + optional geo + type fragment.
    core = _slugify_ascii(base_title, max_len=44)
    pool = list(_SLUG_FRAGMENTS_BY_POST_TYPE.get(post_type) or ["notes", "overview", "briefing", "dispatch", "signals"])
    if vid == "cleaning":
        pool = [p for p in pool if p not in ("dispatch", "internal")]
        if not pool:
            pool = ["routes", "checklist", "floors", "prep", "windows", "notes"]
    frag = rng.choice(pool)
    geo = ""
    if (district or "").strip() and rng.random() < 0.55:
        geo = _slugify_ascii(district, max_len=18)
    elif (city or "").strip() and rng.random() < 0.22:
        geo = _slugify_ascii(city, max_len=18)
    chunk_a = [p for p in (core, frag) if p and p != "post"]
    chunk_b = [p for p in (frag, core) if p and p != "post"]
    ordered = chunk_a if rng.random() < 0.72 else chunk_b
    if geo:
        insert_at = rng.choice([0, len(ordered)])
        ordered = ordered[:insert_at] + [geo] + ordered[insert_at:]
    raw = "-".join(ordered) if ordered else frag
    raw = _dedupe_adjacent_slug_parts(raw)
    anchor = _slugify_ascii(raw, max_len=88).strip("-") or "insight"
    anchor = anchor.replace("how-to", "steps").replace("how_to", "steps")
    anchor = re.sub(r"-{2,}", "-", anchor).strip("-") or "insight"
    anchor = _dedupe_adjacent_slug_parts(anchor)
    anchor = _trim_slug_at_word_boundary(anchor, 78)
    return _slug_tail_cleanup(anchor)


def _unique_slug_in_set(base: str, seen: set[str], *, max_len: int = 72) -> str:
    if base not in seen:
        return base
    n = 0
    candidate = base
    while candidate in seen:
        n += 1
        suffix = _short_hash_token(f"{base}|{n}")
        candidate = _slugify_ascii(f"{base}-{suffix}", max_len=max_len).strip("-") or suffix
    return candidate


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slugify_ascii(text: str, *, max_len: int = 64) -> str:
    s = (text or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _NON_ALNUM.sub("-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        return "post"
    if len(s) > max_len:
        s = _trim_slug_at_word_boundary(s, max_len)
    return s.strip("-") or "post"


def _longform_blog_categories(vertical_id: str) -> list[str]:
    vid = (vertical_id or "").strip()
    pools: dict[str, list[str]] = {
        "marketing_agency": ["SEO", "Analytics", "Content", "Technical", "Strategy", "Case notes"],
        "cafe_restaurant": ["Menu", "Events", "Behind the scenes", "Suppliers", "Wine & NA", "Neighborhood"],
        "cleaning": ["Facilities", "Sanitization", "Operations", "Compliance", "Checklists", "Seasonal"],
        "fitness": ["Training", "Programming", "Coaching", "Mobility", "Nutrition", "Member life"],
        "clothing": ["Drops", "Fit & sizing", "Fabric", "Care", "Lookbook", "Fulfillment"],
        "news": ["Technology", "Business", "World", "Science", "Politics", "Culture", "Health"],
        "accounting": ["Tax", "Bookkeeping", "Payroll", "GST/HST", "CRA", "Year-end", "Advisory"],
        "legal": ["Corporate", "Contracts", "Compliance", "Litigation", "Estates", "Employment"],
    }
    return list(pools.get(vid) or ["Updates", "Playbooks", "Guides", "Field notes", "Behind the scenes"])


def build_blog_authors(
    rng: random.Random,
    brand_name: str,
    vertical_id: str,
    team_items: list[dict[str, Any]] | None = None,
    brand: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    vid = (vertical_id or "").strip()
    if vid == "news":
        # News has its own author generator with tighter newsroom tone.
        return []
    # Prefer authors drawn from the visible team to avoid schema/credibility mismatch.
    if isinstance(team_items, list) and team_items:
        pool: list[dict[str, Any]] = []
        for i, m in enumerate(team_items):
            if not isinstance(m, dict):
                continue
            nm = str(m.get("name") or "").strip()
            if not nm:
                continue
            title = str(m.get("role") or "Team member").strip()
            slug = nm.lower().replace(" ", "-")
            pool.append(
                {
                    "id": f"author-{i + 1}",
                    "slug": slug,
                    "name": nm,
                    "title": title,
                    "bio": str(m.get("bio") or f"{nm} shares practical notes from the {brand_name} team.").strip(),
                    "photo_src": str(m.get("photo_src") or "").strip(),
                }
            )
        if pool:
            rng.shuffle(pool)
            return pool[: rng.choice([2, 3])]
    sk = site_key_from_brand(brand or {})
    seeds: list[tuple[str, str]] = [
        (
            "Editor",
            "Edits for clarity and proof: if a claim can’t be linked or measured, it doesn’t survive the second draft.",
        ),
        (
            "Staff writer",
            f"Writes practical explainers for {brand_name} — fewer slogans, more steps you can actually follow.",
        ),
        (
            "Contributor",
            "Focuses on templates, checklists, and the unglamorous edge cases that break in real life.",
        ),
    ]
    rng.shuffle(seeds)
    take = rng.choice([2, 3])
    authors: list[dict[str, Any]] = []
    for i, (title, bio) in enumerate(seeds[:take]):
        bct = str((brand or {}).get("country") or "").strip() or None
        name = pick_full_name(sk, f"blog|author|{vertical_id}|{i}", country=bct)
        slug = name.lower().replace(" ", "-")
        aid = f"author-{i + 1}"
        authors.append(
            {
                "id": aid,
                "slug": slug,
                "name": name,
                "title": title,
                "bio": bio,
                "photo_src": "",
            }
        )
    return authors


def _longform_section_pack(
    *,
    rng: random.Random,
    brand_name: str,
    city: str,
    country: str,
    activity: str,
    vertical_id: str,
    title: str,
    category: str,
    sources: list[dict[str, str]],
) -> list[dict[str, Any]]:
    def _format_geo(c: str, co: str) -> str:
        c1 = (c or "").strip()
        co1 = (co or "").strip()
        if not c1 and not co1:
            return "your market"
        if not co1:
            return c1
        if c1 and c1.lower() == co1.lower():
            return c1
        return f"{c1}, {co1}".strip(", ")

    def _pick_links(srcs: list[dict[str, str]]) -> tuple[str, str, str]:
        s0 = srcs[0]
        s1 = srcs[1] if len(srcs) > 1 else srcs[0]
        s2 = srcs[2] if len(srcs) > 2 else srcs[0]
        return _a(s0["url"], s0["org"]), _a(s1["url"], s1["org"]), _a(s2["url"], s2["org"])

    vid = (vertical_id or "").strip()
    pack_vid = "legal" if vid == "consulting" else vid
    geo = _format_geo(city or "your market", country)
    link0, link1, link2 = _pick_links(sources)
    tlow = _blog_topic_for_templates(title, activity=activity)
    topic_ref = tlow if len(tlow) <= 40 else "this article"
    if pack_vid == "legal":
        matter_phrase = rng.choice(
            [
                "this matter",
                "the issues outlined above",
                "your file",
                "the subject of this article",
            ],
        )
    elif pack_vid == "accounting":
        matter_phrase = rng.choice(
            [
                "these filings",
                "this engagement",
                "the compliance topics above",
                "this work",
            ],
        )
    else:
        matter_phrase = topic_ref

    _heading_pools: dict[str, list[str]] = {
        "cleaning": [
            f"What {tlow} actually involves",
            f"Scheduling around {tlow}",
            f"Chemistry notes for {tlow}",
            f"Common gaps we find in {tlow}",
            f"Auditing {tlow} results",
            f"Crew handoff notes for {tlow}",
            f"Equipment choices behind {tlow}",
            f"What supervisors check on {tlow}",
            f"Post-service walkthroughs for {tlow}",
            f"How traffic patterns affect {tlow}",
            f"Documentation standards for {tlow}",
            f"Seasonal adjustments to {tlow}",
            f"Client feedback loops on {tlow}",
            f"Safety protocols during {tlow}",
            "Surface types and what changes",
            "A walkthrough of the inspection",
            "What the log should include",
            "When to rescope instead of repeat",
            "Zone priorities on a real route",
            "Signage, access, and crew timing",
        ],
        "cafe_restaurant": [
            f"{tlow} in practice",
            f"What guests should know about {tlow}",
            f"Prep changes tied to {tlow}",
            f"Timing and pacing for {tlow}",
            f"Kitchen protocols behind {tlow}",
            f"What the menu says about {tlow}",
            f"Guest communication around {tlow}",
            f"Sourcing decisions behind {tlow}",
            f"How reservations affect {tlow}",
            f"Service flow when {tlow} is busy",
            f"Staff briefing notes on {tlow}",
            f"Testing changes to {tlow}",
            f"Dietary notes the kitchen tracks for {tlow}",
            f"Seasonal swaps affecting {tlow}",
            f"Waitlist management during {tlow}",
            f"Front-of-house checks on {tlow}",
            f"Temperature and plating for {tlow}",
            f"Beverage pairings with {tlow}",
            f"Private events and {tlow}",
            f"Walk-in handling during {tlow}",
        ],
        "clothing": [
            f"Sizing detail for {tlow}",
            f"Fabric behavior in {tlow}",
            f"Care steps after {tlow}",
            f"What to check before ordering {tlow}",
            f"Color consistency across {tlow} batches",
            f"Shrinkage testing on {tlow}",
            f"Layering options with {tlow}",
            f"Storage and hanger advice for {tlow}",
            f"Tailoring considerations for {tlow}",
            f"Return process for {tlow}",
            f"Shipping timelines for {tlow}",
            f"Photography notes on {tlow}",
            f"Flat vs. on-body measurements for {tlow}",
            f"How color ages on {tlow}",
            f"What changed in the latest {tlow} drop",
            f"Packaging standards for {tlow}",
            f"Photographing {tlow}",
            f"Composition labels on {tlow}",
            f"Seasonal availability of {tlow}",
            f"Wear testing results for {tlow}",
        ],
        "fitness": [
            f"Coaching {tlow} on the floor",
            f"Programming notes for {tlow}",
            f"Common mistakes in {tlow}",
            f"Recovery after {tlow}",
            f"Scaling options for {tlow}",
            f"What a session of {tlow} looks like",
            f"Tracking progress on {tlow}",
            f"When to modify {tlow}",
            f"Equipment setup for {tlow}",
            f"Warm-up sequence before {tlow}",
            f"Coaching cues during {tlow}",
            f"Rest and tempo in {tlow}",
            f"Class cap and coaching ratio for {tlow}",
            f"Movement screening before {tlow}",
            f"Deload structure around {tlow}",
            f"Open gym etiquette during {tlow}",
            f"Trial visit expectations for {tlow}",
            f"Hydration and fueling around {tlow}",
            f"Injury prevention during {tlow}",
            f"Block rotation and {tlow}",
        ],
        "marketing_agency": [
            f"Our approach to {tlow}",
            f"Metrics that matter for {tlow}",
            f"Common pitfalls in {tlow}",
            f"Reporting cadence on {tlow}",
            f"Timeline expectations for {tlow}",
            f"Stakeholder roles in {tlow}",
            f"Quality gates for {tlow}",
            f"Scoping {tlow} deliverables",
            f"Testing and validation for {tlow}",
            f"Client access requirements for {tlow}",
            f"Risk factors in {tlow}",
            f"Post-launch monitoring of {tlow}",
            f"First-week audit steps for {tlow}",
            f"Schema checks related to {tlow}",
            f"Content brief structure for {tlow}",
            f"Release tracking on {tlow}",
            f"Staging gates before {tlow} ships",
            f"Finance-friendly metrics for {tlow}",
            f"When to pause {tlow}",
            f"Handoff documentation for {tlow}",
        ],
        "accounting": [
            f"What {topic_ref} means for GST, HST, or exempt sales",
            f"Bookkeeping checkpoints before we sign off on {matter_phrase}",
            f"Payroll and remittance angles tied to {matter_phrase}",
            f"Year-end accruals and {matter_phrase}",
            f"T-slips and third-party reporting for {matter_phrase}",
            f"CRA correspondence patterns we see around {matter_phrase}",
            f"Shareholder and related-party notes on {matter_phrase}",
            f"Industry-specific wrinkles in {matter_phrase}",
            f"Documentation an auditor expects for {matter_phrase}",
            f"Common misconceptions about {matter_phrase}",
            f"Timing: monthly vs. quarterly work on {matter_phrase}",
            f"Software and data exports that streamline {matter_phrase}",
            f"Alberta and federal layers in {matter_phrase}",
            f"When to escalate {matter_phrase} to a tax specialist",
            f"Closing entries that stabilize {matter_phrase}",
            f"Internal controls that support {matter_phrase}",
            f"Reconciliations before discussing {matter_phrase}",
            f"Client prep that shortens review on {matter_phrase}",
        ],
        "legal": [
            f"How {matter_phrase} shows up in intake",
            f"Risk framing we use when discussing {matter_phrase}",
            f"Timeline and disclosure issues in {matter_phrase}",
            f"Document requests that move {matter_phrase} forward",
            f"When {matter_phrase} needs co-counsel or a specialist",
            f"Written advice vs. verbal guidance on {matter_phrase}",
            f"Confidentiality boundaries around {matter_phrase}",
            f"What clients misunderstand about {matter_phrase}",
            f"Checklists before filings related to {matter_phrase}",
            f"Communicating setbacks on {matter_phrase}",
            f"Scope changes mid-matter on {matter_phrase}",
            f"Coordination with in-house teams on {matter_phrase}",
            f"Preservation and records for {matter_phrase}",
            f"Settlement vs. hearing paths for {matter_phrase}",
            f"Regulatory touchpoints connected to {matter_phrase}",
            f"Fee and milestone planning for {matter_phrase}",
        ],
    }
    _heading_default = [
        "The first two weeks — what actually happens",
        "Before handoff: checks we run",
        "Where engagements drift — and the early warning",
        "Writing decisions so they survive turnover",
        "Quality gates before clients see it",
        "Alignment without calendar soup",
        "Risk registers — weekly, not decorative",
        "Capacity when the calendar is already full",
        "Definition of ready vs. done",
        "Post-mortems that change the playbook",
        "Standardize vs. improvise — quick call",
        "Boring workflow, predictable delivery",
        "Signals it is time to rescope",
        "One accountable owner per thread",
        f"{tlow} in the wider plan",
        f"Common misunderstandings about {tlow}",
        f"After {tlow} ships — what we watch",
        f"Revisiting assumptions behind {tlow}",
        f"Dependencies that usually block {tlow}",
    ]

    heads = list(_heading_pools.get(pack_vid, _heading_default))
    rng.shuffle(heads)
    h1, h2, h3 = heads[:3]

    _lede_templates: dict[str, list[str]] = {
        "cleaning": [
            f"This guide covers {tlow} the way {brand_name} handles it on actual routes in {geo} -- surfaces, timing, and the proof we leave behind.",
            f"Questions about {tlow} come up weekly in {geo}, so {brand_name} put the answer in one page instead of repeating it on every walkthrough.",
            f"Clarity on {tlow} is what property managers in {geo} request most -- this is what {brand_name} crews reference before they start.",
            f"Our approach to {tlow} for commercial sites in {geo} is practical, auditable, and built around the finish on your floors.",
            f"We documented {tlow} after the same questions showed up across three buildings in {geo} the same month.",
            f"The internal reference for {tlow} that {brand_name} uses in {geo} is published here so clients see the same checklist the crew carries.",
            f"Scope, frequency, and proof for {tlow} -- this page addresses all three for buildings in {geo}.",
            f"Procedures for {tlow} were requested by building teams in {geo}, so {brand_name} published what crews actually follow.",
            f"Before a first walkthrough on {tlow}, {brand_name} shares this page so expectations in {geo} are set before any crew arrives.",
            f"These notes on {tlow} come from real routes {brand_name} runs in {geo} -- not marketing copy or industry generalizations.",
            f"When asked about {tlow}, we send this page instead of a long email chain -- it covers what {brand_name} does in {geo}.",
            f"How {tlow} plays out varies by building, but the default process for {geo} starts with what is outlined here.",
        ],
        "cafe_restaurant": [
            f"Guests in {geo} often ask about {tlow} -- this page is the honest version of what {brand_name} can (and cannot) accommodate.",
            f"Details on {tlow} come up weekly at {brand_name}, and a clear page beats a rushed explanation mid-service.",
            f"How {tlow} works from the kitchen perspective at {brand_name} in {geo} -- read this before your visit.",
            f"This note on {tlow} reflects how {brand_name} actually runs service in {geo} -- timing, sourcing, and the constraints we work around.",
            f"Anyone researching {tlow} before booking at {brand_name} will find the same detail we share with event planners.",
            f"Our position on {tlow} is documented here so the front-of-house team in {geo} and guests are on the same page.",
            f"Transparency on {tlow} matters to {brand_name} -- this page explains the how and why behind our approach in {geo}.",
            f"Clarity on {tlow} for first-time visitors at {brand_name} in {geo} -- the same detail regulars already know.",
            f"Questions about {tlow} account for most of the calls {brand_name} gets in {geo}, so we put the answer here.",
            f"Service standards for {tlow} at {brand_name} are documented so every shift in {geo} delivers the same experience.",
            f"The kitchen team at {brand_name} drafted this note on {tlow} for guests who prefer to know what happens behind the pass.",
            f"If {tlow} is part of why you chose {brand_name} in {geo}, this page explains exactly what to expect.",
        ],
        "clothing": [
            f"Shoppers in {geo} ask about {tlow} more than anything else, so {brand_name} put the answer where everyone can find it.",
            f"This guide on {tlow} replaces the one-line FAQ -- it covers fit, care, and the edge cases that cause returns.",
            f"Before ordering from {brand_name}, here is what you should know about {tlow}: measurements, materials, and post-wash expectations.",
            f"Repeated questions about {tlow} across three drops in {geo} prompted {brand_name} to write this guide.",
            f"Comparing brands on {tlow}? This page gives you the numbers {brand_name} stands behind.",
            f"Fit notes on {tlow} are published because email exchanges about sizing slow everyone down.",
            f"Our approach to {tlow} starts with the fabric and ends with a care label you can actually follow.",
            f"Details on {tlow} below are tested on production samples -- not written from spec sheets alone.",
            f"The {tlow} page exists because customer service kept answering the same five questions in {geo}.",
            f"Whether you are buying {tlow} for the first time or reordering, the sizing and care notes below apply.",
            f"Fabric, fit, and care for {tlow} -- {brand_name} documents everything so returns stay low.",
            f"How {brand_name} approaches {tlow} in {geo}: honest measurements, tested care instructions, and clear return terms.",
        ],
        "fitness": [
            f"Members in {geo} ask about {tlow} every week -- here is how {brand_name} coaches it on the floor.",
            f"This guide covers {tlow} the way {brand_name} programs it: warm-up, execution, and what to track.",
            f"New to {brand_name} in {geo}? The question about {tlow} comes up first -- this page is the full answer.",
            f"Trials and on-ramp sessions at {brand_name} in {geo} always surface {tlow}, so we documented it.",
            f"Coaching cues, scaling options, and form standards for {tlow} -- all in one place from {brand_name}.",
            f"Programming for {tlow} at {brand_name} is updated every training block; this page tracks the current version.",
            f"The coaches at {brand_name} in {geo} wrote this so members stop guessing about {tlow} between sessions.",
            f"How {tlow} fits into your week depends on training frequency -- this guide from {brand_name} explains the options.",
            f"Our position on {tlow} is practical: here is what works for most members at {brand_name} in {geo}.",
            f"Questions about {tlow} during class eat into coaching time, so {brand_name} put the answer here.",
            f"How {brand_name} programs {tlow} for members in {geo} -- progression, scaling, and when to back off.",
            f"If {tlow} is new to you, read this before your first session at {brand_name} in {geo}.",
        ],
        "marketing_agency": [
            f"Clients in {geo} ask about {tlow} before every engagement -- this page is {brand_name} standing answer.",
            f"This guide documents how {brand_name} approaches {tlow}: the audit steps, the metrics, and the handoff.",
            f"Evaluating agencies for {tlow}? Here is what {brand_name} checks first and why.",
            f"Three discovery calls in {geo} covered the same {tlow} questions, so {brand_name} wrote this guide.",
            f"The checklist, the reporting, and common pitfalls for {tlow} -- from {brand_name} client engagements.",
            f"How {brand_name} scopes {tlow} for clients in {geo}: timeline, deliverables, and what we need from your side.",
            f"Agencies talk about {tlow} differently; this page shows how {brand_name} actually delivers it.",
            f"How {brand_name} structures {tlow} engagements in {geo} -- read this before signing with any agency.",
            f"Our process for {tlow} is documented so clients and internal teams reference the same playbook.",
            f"Transparency on {tlow} reduces scope disputes later -- {brand_name} publishes the method, not just results.",
            f"The {tlow} framework below is what {brand_name} runs for clients in {geo}; we update it quarterly.",
            f"If {tlow} is on your roadmap, this page explains how {brand_name} approaches it from day one.",
        ],
        "accounting": [
            f"This article walks through {topic_ref} the way {brand_name} prepares files for review in {geo} — reconciliations, source documents, and CRA-facing clarity.",
            f"Clients in {geo} ask about {topic_ref} every tax season; {brand_name} wrote this so intake stays consistent and deadlines do not slip.",
            f"We published notes on {topic_ref} after the same GST and payroll questions surfaced across engagements in {geo}.",
            f"Practical guidance on {topic_ref} from {brand_name}: what we need from you, what we file, and what we keep in the workpaper pack.",
            f"If {topic_ref} affects your remittances or instalments, the sequence below matches how {brand_name} sequences month-end in {geo}.",
            f"This is not generic tax talk — {topic_ref} here reflects Alberta and federal rules as {brand_name} applies them for clients in {geo}.",
            f"Questions on {topic_ref} belong in one place; {brand_name} points clients here before we book deep-dive time.",
            f"Below, {topic_ref} is broken into bookkeeping, tax, and documentation habits {brand_name} uses in {geo}.",
            f"We revisit {topic_ref} when CRA publishes updates; the date on this article is your freshness cue.",
            f"Whether you are a sole proprietor or a corporation, {topic_ref} starts with clean records — {brand_name} explains the bar we use in {geo}.",
            f"After several filings touched {topic_ref}, {brand_name} documented the checklist we actually run internally.",
            f"Use this page on {topic_ref} to align your team before month-end; it mirrors how {brand_name} closes books in {geo}.",
        ],
        "legal": [
            f"This article explains how {brand_name} approaches {topic_ref} for clients in {geo} — written scope, clear risk calls, and files you can hand to regulators or counterparties.",
            f"We hear recurring questions about {topic_ref}; {brand_name} published this so expectations match how we practice in {geo}.",
            f"Notes on {topic_ref} from {brand_name}: what we need at intake, how we staff matters, and how we communicate timelines.",
            f"If {topic_ref} is on your radar, read this before the first consultation — it saves duplicate emails and speeds drafting.",
            f"Practical guidance on {topic_ref}, not slogans: how {brand_name} documents advice and tracks open issues in {geo}.",
            f"Clients in {geo} use this page on {topic_ref} as a shared reference when multiple stakeholders review decisions.",
            f"We wrote about {topic_ref} after similar matters surfaced the same document gaps three months in a row.",
            f"Transparency on {topic_ref} reduces disputes later — {brand_name} outlines roles, deliverables, and what we do not promise.",
            f"The sections below on {topic_ref} reflect current practice at {brand_name}; processes change when rules or courts move.",
            f"Whether you are an operator or in-house counsel, {topic_ref} here is written to align teams before work gets expensive.",
            f"After parallel intakes on {topic_ref}, {brand_name} consolidated the questions we ask every time.",
            f"This page on {topic_ref} is the brief we want clients to read before signing retainers in {geo}.",
        ],
    }
    _lede_default = [
        f"This piece explains how {brand_name} thinks about {tlow} for teams in {geo} — concrete steps, not slogans.",
        f"We hear the same questions about {tlow} from clients in {geo}; {brand_name} put the answers in one place.",
        f"If {tlow} is on your roadmap, here is how {brand_name} approaches it: priorities first, constraints named early.",
        f"After three similar conversations on {tlow} in one week, {brand_name} wrote this so everyone starts from the same map.",
        f"Notes on {tlow} from {brand_name} — written for people who need to act this quarter, not debate forever.",
        f"How {brand_name} runs {tlow} in {geo}: what we optimize for, what we refuse to rush, and what clients should expect.",
        f"We publish this on {tlow} so clients and our own team point to the same wording when decisions get reviewed.",
        f"What follows on {tlow} matches how {brand_name} actually works in {geo}, not a pitch deck version.",
        f"Practical guidance on {tlow} from {brand_name} — tied to real engagements, revised when our process changes.",
        f"Kickoff meetings kept circling {tlow}; this page is {brand_name}'s standing brief so time stays on execution.",
        f"We stopped re-explaining {tlow} in slide decks — this article is the shortcut {brand_name} sends instead.",
        f"Below, {brand_name} walks through {tlow} for readers in {geo}: sequence, rationale, and a sensible place to start.",
    ]

    lede = rng.choice(_lede_templates.get(pack_vid, _lede_default))

    _p2_templates = [
        f"For context on {topic_ref}, we cross-reference sources like {link0}, {link1}, and {link2} before publishing.",
        f"Where claims about {topic_ref} need backing, we lean on {link0}, {link1}, and {link2}.",
        f"The guidance on {topic_ref} below draws on practical experience and public references including {link0}, {link1}, and {link2}.",
        f"External anchors for {topic_ref} — {link0}, {link1}, and {link2} — help verify advice before it ships.",
        f"References we revisit most for {topic_ref}: {link0}, {link1}, and {link2}.",
        f"Before publishing on {topic_ref}, we check facts against {link0}, {link1}, and {link2}.",
        f"This article is backed by references we trust: {link0}, {link1}, and {link2}.",
        f"Accuracy matters for what we discuss here, so we verify against sources like {link0}, {link1}, and {link2}.",
        f"Three resources that inform our position: {link0}, {link1}, and {link2}.",
        f"Published standards from {link0}, {link1}, and {link2} anchor what we recommend in the sections below.",
        f"Fact-checking runs through {link0}, {link1}, and {link2} before anything goes live.",
        f"Our editors check this topic against {link0}, {link1}, and {link2} during review.",
        f"Reliable guidance requires reliable sources — {link0}, {link1}, and {link2} are the ones we return to.",
        f"Claims below trace back to at least one of these: {link0}, {link1}, or {link2}.",
        f"When drafting, we reference {link0}, {link1}, and {link2} to stay grounded.",
    ]
    p2 = rng.choice(_p2_templates)

    _p3_pools: dict[str, list[str]] = {
        "cleaning": [
            f"Guidance on {tlow} here is a starting point for {geo} -- traffic patterns and finishes vary by building.",
            f"Adjust the cadence on {tlow} after the first two inspection cycles -- every building in {geo} is different.",
            f"This is baseline guidance for {tlow} in {geo} -- edge cases depend on surface type, access hours, and tenant mix.",
            f"Pair {tlow} notes with your existing scope documents; this is one piece of a broader route plan.",
            f"Defaults for {tlow} here are starting points -- walk the site first, because no guide replaces seeing the floors.",
            f"Use {tlow} details below as a reference for discussions with your facility team, not a final contract scope.",
            f"Variables like HVAC, flooring age, and shift patterns affect {tlow} more than any general guide can capture.",
            f"A credible starting point for {tlow} conversations is what this page offers property managers in {geo}.",
            f"On-site conditions dictate the real schedule for {tlow}; what follows is a reasonable default for {geo}.",
            f"How {tlow} plays out depends on tenant density, flooring age, and shift timing in your building.",
            f"No two routes for {tlow} look the same -- review these notes after the first month and adjust.",
            f"These recommendations for {tlow} assume a standard commercial building in {geo}; adjust for specialty spaces.",
            f"Standard-case steps for {tlow} are below; unusual surfaces or schedules may require a site visit.",
            f"Operational details for {tlow} shift with seasons, tenant turnover, and building age -- revisit quarterly.",
        ],
        "cafe_restaurant": [
            f"Baseline notes on {tlow} for visitors to {brand_name} in {geo} -- the contact page has current hours.",
            f"Seasonal changes affect {tlow}; we update this page when the menu or format changes.",
            f"Event bookings and large parties for {tlow} in {geo} require direct contact -- this page covers regular service.",
            f"Practical detail on {tlow}, not marketing copy -- we publish it so expectations match reality.",
            f"The notes on {tlow} below reflect a standard evening service at {brand_name} in {geo}.",
            f"Peak nights can affect how {tlow} is handled; the contact page has real-time availability.",
            f"Dietary constraints around {tlow} should be mentioned at booking -- the kitchen plans accordingly.",
            f"How {tlow} works at {brand_name} may differ from other restaurants in {geo}; this is our process.",
            f"Specifics on {tlow} for private events differ from regular service -- ask the events team directly.",
            f"Shift briefings on {tlow} happen before doors open at {brand_name}; this page reflects what servers tell guests.",
            f"Menu changes affect {tlow} seasonally; the most current version is always on this page.",
            f"First-time guests at {brand_name} in {geo} find this page on {tlow} helpful before they arrive.",
            f"If {tlow} is a priority for your visit, calling ahead gives {brand_name} time to prepare properly.",
            f"These details on {tlow} come from the kitchen and floor teams at {brand_name}, not from a copywriter.",
        ],
        "clothing": [
            f"Between sizes on {tlow}? Start with flat measurements against a garment you already own.",
            f"The measurement chart and care label for {tlow} are more reliable than on-body photos alone.",
            f"Returns on {tlow} are simpler when tags are intact and items were tried on indoors.",
            f"Fabric behavior on {tlow} changes with washing; we test pre-wash shrinkage and publish adjusted dimensions.",
            f"Color on {tlow} may vary slightly between batches; we note shifts when they affect the product.",
            f"How {tlow} fits depends on your body type -- the size guide below covers common proportions.",
            f"Layering with {tlow} works best when you know the intended drape; the notes below explain it.",
            f"We update {tlow} details after each production run, so what you read here matches current stock.",
            f"Shipping timelines for {tlow} are estimates; peak periods add one to two business days.",
            f"Trying {tlow} indoors first preserves the option to return -- outdoor wear voids the return window.",
            f"If {tlow} looks different on screen, adjust monitor brightness; the studio shots use calibrated lighting.",
            f"Composition labels on {tlow} tell part of the story; the care notes below cover what the label cannot.",
            f"Reorders of {tlow} may arrive with minor textile differences; we flag batch changes on the product page.",
            f"Measurements for {tlow} are taken post-wash so numbers reflect what you actually wear, not what ships.",
        ],
        "fitness": [
            f"Trialing at {brand_name} in {geo}? Ask a coach to walk you through {tlow} before your first class.",
            f"Programming for {tlow} evolves block to block -- this page reflects the current cycle.",
            f"Scaling on {tlow} is always available; coaches adjust in real time based on your movement.",
            f"Track {tlow} progress week over week; consistency matters more than intensity on any single day.",
            f"How {tlow} fits into the weekly schedule depends on your training frequency and recovery capacity.",
            f"Coaches at {brand_name} modify {tlow} for injuries and limitations -- communicate before class starts.",
            f"The notes on {tlow} below assume a general fitness background; beginners get additional scaling.",
            f"Rest days around {tlow} are as important as the sessions; the programming accounts for both.",
            f"Equipment for {tlow} is shared during peak hours -- arrive a few minutes early to set up.",
            f"If {tlow} feels too easy or too hard, tell the coach; the prescription should match your current level.",
            f"Progress on {tlow} stalls when volume increases too fast; the periodization below prevents that.",
            f"Members who are new to {tlow} at {brand_name} in {geo} benefit from a movement assessment first.",
            f"Warm-up notes for {tlow} are non-negotiable; skipping them increases injury risk for no good reason.",
            f"These recommendations for {tlow} are based on what works for most members, not elite athletes.",
        ],
        "marketing_agency": [
            f"Comparing agencies on {tlow} in {geo}? Ask how they document it -- not just what they promise.",
            f"Timelines for {tlow} depend on access, scope, and stakeholder availability; we estimate conservatively.",
            f"Every engagement on {tlow} is different, but the process below is the default starting point at {brand_name}.",
            f"Clients reviewing {tlow} options should read this before the discovery call.",
            f"How {tlow} is delivered depends on your existing tech stack and data access -- we audit both first.",
            f"The scope document for {tlow} is shared before work begins so both sides know the deliverables.",
            f"Reporting cadence on {tlow} matches your internal review cycle; we adapt, not dictate.",
            f"If {tlow} overlaps with work another vendor handles, {brand_name} coordinates handoff explicitly.",
            f"These {tlow} steps assume a standard engagement in {geo}; enterprise accounts get a custom scope.",
            f"Delivering {tlow} requires analytics and CMS access upfront -- delays here delay the entire timeline.",
            f"The {tlow} framework below is reviewed quarterly; what you read matches our current methodology.",
            f"Stakeholder alignment on {tlow} before kickoff prevents the scope creep that drags engagements out.",
            f"Results from {tlow} compound over time; the first month is setup, the second is measurement, the third is optimization.",
            f"Before committing to {tlow} with any agency, verify that they define done in measurable terms.",
        ],
        "accounting": [
            f"Tax positions on {matter_phrase} depend on facts — this article is a starting point, not a substitute for engagement-specific advice in {geo}.",
            f"Provincial and federal rules both touch {matter_phrase}; when they conflict, we document the filing position before anything is submitted.",
            f"If your books are behind, {matter_phrase} takes longer — catch up first, then refine elections and instalments with clean numbers.",
            f"Use the notes on {matter_phrase} alongside your accountant’s year-end package; edge cases need a scoped conversation.",
            f"CRA correspondence on {matter_phrase} should be dated and filed; we keep a single thread per issue so responses stay coherent.",
            f"GST and HST angles on {matter_phrase} change with your registration status and supply mix — verify both before you rely on defaults.",
            f"Payroll and contractor characterization affect {matter_phrase}; misclassification is expensive to unwind after T4 season.",
            f"Alberta corporate rules and federal T2 filings both influence {matter_phrase}; timelines assume both layers are in scope.",
            f"Software exports help, but {matter_phrase} still needs judgment — maps from the bank feed to the GL are not automatic truth.",
            f"We refresh this guidance on {matter_phrase} when CRA or Finance publishes interpretive changes; check the publish date.",
            f"Records for {matter_phrase} should be contemporaneous; reconstructed spreadsheets rarely survive scrutiny.",
            f"If {matter_phrase} touches related parties, document pricing and terms before year-end closes.",
            f"Instalments and remittances tied to {matter_phrase} have different due dates — missing one does not excuse the other.",
            f"Non-profits reading about {matter_phrase} should pair this with restricted-fund policies; charity rules add another layer.",
        ],
        "legal": [
            f"Nothing here on {matter_phrase} creates a solicitor–client relationship; specifics depend on your facts and jurisdiction in {geo}.",
            f"Laws and tribunal rules affecting {matter_phrase} change; treat this page as orientation, not a substitute for current research.",
            f"If {matter_phrase} overlaps litigation and regulatory risk, parallel tracks need one coordinated strategy — not two silent teams.",
            f"Document preservation for {matter_phrase} starts early; spoliation issues are harder to fix than to prevent.",
            f"Deadlines in {matter_phrase} matters are often non-negotiable; calibrate staffing before you promise a simultaneous filing.",
            f"In-house counsel and external firms both need the same fact base on {matter_phrase}; divergent binders create expensive drift.",
            f"Settlement discussions on {matter_phrase} should be labeled clearly so privilege and without-prejudice protections actually apply.",
            f"Multi-party matters need a single document index for {matter_phrase}; version chaos is how deadlines get missed.",
            f"If {matter_phrase} touches employment, privacy, or securities law, specialists may be required — we flag that early.",
            f"Clients in {geo} should confirm regulatory references still apply; municipal and provincial overlays vary.",
            f"Written risk assessments on {matter_phrase} age; revisit after material facts change or new disclosure arrives.",
            f"Retainers for {matter_phrase} should spell out assumptions, exclusions, and escalation paths before work accelerates.",
            f"Cross-border aspects of {matter_phrase} need local counsel; this article assumes primarily Canadian practice patterns.",
            f"Emergency steps on {matter_phrase} belong on a one-page checklist — not buried in a long email chain.",
        ],
    }
    _p3_default = [
        f"Planning work on {tlow}? Treat the steps below as a baseline for your context in {geo}.",
        f"Edge cases around {tlow} exist — we flag them instead of pretending one article covers every scenario.",
        f"Use the sections below as a starting framework for {tlow}; your constraints should bend the details, not skip the basics.",
        f"The aim here is the 80 percent of {tlow} that most teams in {geo} share — not every outlier at once.",
        f"How {tlow} plays out depends on team size, budget, and timeline — read accordingly.",
        f"These notes on {tlow} assume a typical engagement; unusual constraints usually need a scoped conversation.",
        f"What works for {tlow} in {geo} may need tuning elsewhere — markets and regulations differ.",
        f"We revise this guidance on {tlow} when our process changes; the publish date shows how fresh it is.",
        f"Past client feedback on {tlow} shaped the recommendations you see here.",
        f"If {tlow} is new for your group, move in order — later sections assume you read the first.",
        f"Real constraints on {tlow} are acknowledged below; the steps target the blockers we see most often.",
        f"Where you are starting from changes the emphasis on {tlow}; use the contact page for anything situational.",
        f"No two {tlow} situations match exactly, but the pattern below is the one we plan against by default.",
        f"Skim {tlow} with your team before you implement — cheap alignment beats expensive rework.",
    ]
    p3 = rng.choice(_p3_pools.get(pack_vid, _p3_default))

    _body_pools: dict[str, list[list[str]]] = {
        "cleaning": [
            [f"For {tlow}, we start by identifying the surface type -- VCT, LVT, sealed concrete, or stone -- and matching chemistry accordingly.", f"Getting the dilution ratio right on {tlow} prevents residue buildup that looks like laziness but is actually a process mistake."],
            [f"Frequency for {tlow} depends on foot traffic, not calendar defaults.", f"High-traffic lobbies during {tlow} may need weekly attention while storage corridors can go monthly."],
            [f"Documentation for {tlow} starts with photos -- same angle, same lighting, every visit.", f"This approach on {tlow} makes quality visible to facility managers who cannot walk every floor."],
            [f"When crews rotate on {tlow}, written chemistry notes prevent the new person from damaging the finish.", f"A color-coded microfiber system during {tlow} adds another layer of contamination prevention."],
            [f"Seasonal deep cleans for {tlow} should be scoped separately from daily routes.", f"Trying to extend a daily {tlow} routine into a deep-clean scope almost always underdelivers."],
            [f"Signage and barriers for {tlow} go up before the first pass, not after a slip complaint.", f"SDS binders for {tlow} should be at every supply station, not just the main office."],
            [f"Restroom protocols for {tlow} require a separate set of tools and chemistry from general floor work.", f"Cross-contamination during {tlow} is the most common audit flag we see in multi-tenant buildings."],
            [f"Carpet extraction schedules for {tlow} depend on fiber type and tenant density, not a fixed quarterly calendar.", f"Spot-treating stains related to {tlow} within 24 hours prevents most permanent marks."],
            [f"Glass and partition cleaning for {tlow} uses lint-free tools so streaks do not appear under office lighting.", f"Internal windows during {tlow} are often skipped; adding them to the route prevents complaints before they start."],
            [f"Elevator detailing for {tlow} includes door tracks, button panels, and cab walls -- areas tenants touch constantly.", f"Stairwell cleaning for {tlow} focuses on handrails and landings where dust and debris collect fastest."],
            [f"Odor control for {tlow} relies on source removal, not masking agents that fade in hours.", f"Drain maintenance during {tlow} is the most overlooked cause of persistent facility smells."],
            [f"Post-construction cleanup for {tlow} requires a phased approach: rough clean, detail clean, then final punch.", f"Dust from renovation during {tlow} migrates through HVAC if containment is not set up before work begins."],
        ],
        "cafe_restaurant": [
            [f"Allergen verification for {tlow} happens at prep, not at the table -- each ticket is flagged.", f"The kitchen cross-checks dietary constraints for {tlow} against the allergen matrix every service."],
            [f"Pacing for {tlow} requires rehearsed transitions between the pass and the floor.", f"Large parties during {tlow} get timing confirmed and dietary notes collected before the first cover."],
            [f"Seasonal swaps for {tlow} are communicated to servers before service opens.", f"When produce peaks during {tlow}, the menu shortens to keep quality consistent."],
            [f"Wine and non-alcoholic pairings for {tlow} are reviewed together so recommendations stay honest.", f"The sommelier adjusts {tlow} pairings when seasonal dishes change the flavor profile."],
            [f"Mise en place for {tlow} is audited before doors open to prevent mid-rush scrambles.", f"Plate temperatures for {tlow} are checked at the pass; timing means nothing if the dish arrives cold."],
            [f"Reservation confirmations for {tlow} include party size and timing so the kitchen can prep.", f"Walk-in management during {tlow} uses realistic wait estimates, not optimistic guesses."],
            [f"Server briefings on {tlow} cover specials, modifications, and anything 86'd before the first seating.", f"The front-of-house script for {tlow} is updated nightly so guests get accurate answers."],
            [f"Private events involving {tlow} get a dedicated timeline from setup to breakdown.", f"The events team at {brand_name} shares {tlow} logistics in writing so nothing is improvised on the night."],
            [f"Sourcing for {tlow} prioritizes local suppliers in {geo} when the quality meets our standard.", f"Menu costing on {tlow} is reviewed monthly; ingredient price swings affect what stays on the plate."],
            [f"Dish photography for {tlow} happens under service conditions, not studio lighting.", f"What you see on the menu or website for {tlow} is what the kitchen actually sends out nightly."],
            [f"Table turnover for {tlow} is paced so no guest feels rushed, even on high-volume nights.", f"The host manages {tlow} timing by staggering seatings at 15-minute intervals."],
            [f"Kitchen closing time for {tlow} is posted and respected; last orders are taken accordingly.", f"Post-service {tlow} prep for the next day starts immediately -- that is how consistency scales."],
        ],
        "clothing": [
            [f"Flat measurements for {tlow} are the most reliable comparison -- lay a similar garment on a table and measure.", f"On-body photos of {tlow} add context but do not replace centimeters."],
            [f"Fabric composition for {tlow} hints at stretch and wrinkle recovery, but weave and finish change the feel.", f"Batch-specific dye shifts on {tlow} are noted when they occur."],
            [f"Care for {tlow}: cold wash, low heat, and reshaping seams while damp prevents most surprises.", f"Knits from the {tlow} line should hang on padded hangers to avoid shoulder dimples."],
            [f"Returns for {tlow} are straightforward when packaging is intact and items were tried indoors.", f"The process for {tlow} returns: contact form, order reference, prepaid label within two business days."],
            [f"Shipping cutoffs for {tlow} are based on carrier handoff, not label creation time.", f"Peak-volume weeks can add a day of lag on {tlow} between scan and movement."],
            [f"Layering for {tlow} works best when each piece has a clear role: base, insulation, outer.", f"Pre-wash shrinkage on {tlow} is tested before we publish measurements."],
            [f"Sizing consistency across {tlow} runs is a priority; we re-measure every production batch.", f"When a {tlow} batch runs slightly different, the product page flag is updated."],
            [f"Color representation for {tlow} is photographed under standardized studio lighting.", f"Monitor calibration affects how {tlow} looks on your screen; the studio shots are the reference."],
            [f"Durability testing for {tlow} includes wash cycles, pilling tests, and seam stress.", f"We publish wear-test results for {tlow} so expectations match reality."],
            [f"Tailoring recommendations for {tlow} are included when the silhouette benefits from adjustment.", f"Not every {tlow} item needs tailoring -- the fit notes indicate when it makes a difference."],
            [f"Seasonal availability for {tlow} varies; core items restock, limited runs do not.", f"Waitlist signup for {tlow} is available on sold-out product pages."],
            [f"Packaging for {tlow} ships flat to reduce creasing; the garment relaxes within a day of unboxing.", f"Recycled materials are used for {tlow} packaging where they do not compromise product protection."],
        ],
        "fitness": [
            [f"Coaching {tlow} starts with form corrections during the warm-up, not mid-set when fatigue competes.", f"Scaling for {tlow} is available at every level; coaches adjust in real time."],
            [f"Equipment for {tlow} is logged on the same maintenance cycle as membership records.", f"Boring admin around {tlow} prevents the expensive injury."],
            [f"Class caps for {tlow} protect coaching quality when attendance spikes unexpectedly.", f"Trial visitors doing {tlow} get a movement screen so recommendations are honest."],
            [f"Rest intervals during {tlow} are programmed explicitly, not treated as filler.", f"Progressive overload on {tlow} means adding stimulus systematically, not piling on weight each session."],
            [f"Deload weeks for {tlow} are scheduled in advance to protect joints and sustain progress.", f"Gym etiquette during {tlow}: strip bars, share racks during peaks, wipe benches after use."],
            [f"Tracking {tlow} week to week matters more than chasing a single heroic session.", f"A simple log for {tlow} -- weight, reps, and how movement felt -- is enough to guide progression."],
            [f"Warm-up structure for {tlow} includes mobility, activation, and a build-up set.", f"Skipping the warm-up before {tlow} increases injury risk without saving meaningful time."],
            [f"Recovery recommendations after {tlow} depend on training volume and sleep quality.", f"Nutrition timing around {tlow} matters less than total daily intake for most members."],
            [f"Movement substitutions for {tlow} are documented on the whiteboard before class starts.", f"Coaches post {tlow} scaling options so members choose the right level without asking mid-set."],
            [f"Heart rate zones during {tlow} are used as guidance, not gospel -- perceived effort also matters.", f"If {tlow} leaves you unable to recover before the next session, the dose is too high."],
            [f"Programming for {tlow} rotates emphasis across strength, endurance, and skill every training block.", f"The variety in {tlow} programming prevents plateaus and keeps members engaged long-term."],
            [f"Partner or team formats for {tlow} are scheduled to build community, not just training stimulus.", f"Communication during partner {tlow} sessions is coached explicitly -- it is part of the workout."],
        ],
        "marketing_agency": [
            [f"The first step for {tlow} is analytics access, Search Console, and a stakeholder list.", f"Onboarding for {tlow} requires enough people to make decisions, not so many that every round needs a deck."],
            [f"Schema validation for {tlow} runs automatically on deploy.", f"Broken structured data on {tlow} pages is caught before it reaches the index."],
            [f"Reporting for {tlow} defaults to metrics your finance team already uses.", f"Shipped work on {tlow} is changelogged so results trace to specific releases."],
            [f"Content briefs for {tlow} include intent mapping, not just keywords.", f"Writers working on {tlow} need the page purpose, not a list of terms to stuff."],
            [f"A/B test sample sizes for {tlow} are calculated before launch.", f"Without statistical significance, {tlow} test results are just a coin flip with a dashboard."],
            [f"Technical audits for {tlow} check crawl budget allocation.", f"If important {tlow} pages are not indexed promptly, traffic projections are fiction."],
            [f"Backlink profiles for {tlow} are audited before any outreach begins.", f"Cleaning up toxic links on {tlow} pages happens before building new ones."],
            [f"Competitor analysis for {tlow} identifies gaps in content, not just keyword overlap.", f"The output of {tlow} competitor research is a prioritized list, not a wall of data."],
            [f"Page speed audits for {tlow} focus on Core Web Vitals that affect ranking.", f"Fixes for {tlow} page speed are shipped in order of impact, not complexity."],
            [f"Conversion tracking for {tlow} is validated end-to-end before any campaign spends budget.", f"Attribution models for {tlow} are documented so everyone interprets the same numbers."],
            [f"Quarterly reviews for {tlow} compare actuals against the forecast shared at kickoff.", f"If {tlow} results diverge from plan, the review identifies whether the assumption or the execution was wrong."],
            [f"Knowledge transfer on {tlow} is structured so your team can maintain the work if the engagement ends.", f"Documentation for {tlow} lives in your systems, not ours -- that is the handoff standard."],
        ],
        "accounting": [
            [f"For {matter_phrase}, we reconcile bank, clearing, and card accounts before discussing tax positions — otherwise conclusions are fiction.", f"Month-end for {matter_phrase} includes prepaid and accrual entries so margins are not distorted by timing noise."],
            [f"GST and HST on {matter_phrase} need a trail from invoice to return line; auditors ask for the map, not a verbal story.", f"Exempt vs. zero-rated supplies change how we approach {matter_phrase}; we confirm registration and supply type before filing."],
            [f"T4 and T5 packages for {matter_phrase} are checked against payroll journals and dividend resolutions — mismatches trigger CRA matching.", f"For contractors tied to {matter_phrase}, we verify T4A vs. T5018 expectations before year-end."],
            [f"Corporate instalments affecting {matter_phrase} are modeled against actual income; underpaying invites non-deductible interest.", f"Loss carryforwards and SR&ED claims can intersect with {matter_phrase}; we document methodology in the workpapers."],
            [f"Shareholder loan balances in {matter_phrase} need promissory notes and repayment evidence — subsection 15(2) is unforgiving.", f"Related-party pricing for {matter_phrase} should be contemporaneous; after-the-fact memos rarely hold up."],
            [f"Motor vehicle and home-office claims for {matter_phrase} require logs and floor plans; rounded percentages invite adjustments.", f"Meals and entertainment caps still matter for {matter_phrase}; the GL needs separate lines."],
            [f"Inventory and COGS for {matter_phrase} are cut off at year-end with physical counts or rolling perpetual reconciliations.", f"Cut-off errors on {matter_phrase} inflate income one year and deflate the next — we tie receiving logs to invoices."],
            [f"Trust accounting for {matter_phrase} keeps client funds segregated; mixing pools is a regulatory issue, not just a cleanup.", f"Bank recs for trust work on {matter_phrase} are done monthly so variances do not compound."],
            [f"Non-profit restricted funds in {matter_phrase} need donor intent on file; unrestricted sweeps without board minutes are a red flag.", f"Functional expense allocations for {matter_phrase} should match how the organization actually spends time."],
            [f"Payroll remittances for {matter_phrase} are matched to PD7A notices; late remitters pay penalties that are rarely waived.", f"Benefits taxable under {matter_phrase} belong on T4s in the right boxes — phantom income surprises employees."],
            [f"Year-end work on {matter_phrase} includes deferred revenue and unbilled AR scrub; otherwise tax income and book income diverge for no good reason.", f"For {matter_phrase}, we close the loop with adjusting entries posted before the T2 is drafted."],
            [f"CRA queries on {matter_phrase} get a single response package: issue list, facts, law, and requested relief — scattershot replies extend audits.", f"We never speculate in writing on {matter_phrase}; drafts go through review before they leave the firm."],
        ],
        "legal": [
            [f"Intake for {matter_phrase} captures conflicts, urgency, and decision-makers before research hours burn.", f"Without a signed retainer scope, work on {matter_phrase} expands informally — we fix that on day one."],
            [f"Document requests for {matter_phrase} are staged: core productions first, follow-ups after initial review.", f"Overbroad fishing on {matter_phrase} slows tribunals; targeted requests preserve credibility."],
            [f"Risk memos on {matter_phrase} separate likelihood from impact so clients can choose among priced options.", f"We avoid definitive predictions on {matter_phrase}; we give ranges and assumptions instead."],
            [f"Litigation holds for {matter_phrase} go to IT and operations, not just legal — silent deletions create exposure.", f"Preservation letters related to {matter_phrase} are dated, specific, and copied to people who control servers."],
            [f"Settlement authority for {matter_phrase} is confirmed in writing before mediations; improvised caps waste the day.", f"Without-prejudice labels in {matter_phrase} discussions are used consistently or privilege arguments fail."],
            [f"Regulatory filings touching {matter_phrase} are calendar-driven; we build buffer before hard statutory deadlines.", f"Parallel civil and regulatory tracks on {matter_phrase} need one partner accountable for both."],
            [f"Contract review for {matter_phrase} flags indemnities, caps, and notice windows — not just spelling.", f"Change-control for {matter_phrase} amendments prevents handshake drift that courts dislike."],
            [f"Employment aspects of {matter_phrase} require up-to-date statutes; template clauses age faster than people expect.", f"Workplace investigations related to {matter_phrase} need neutral scoping and prompt timelines."],
            [f"Estates work on {matter_phrase} needs capacity notes and will provenance before distributions are discussed.", f"Undue influence risks around {matter_phrase} are documented early, not after beneficiaries fight."],
            [f"Corporate minutes for {matter_phrase} should match what actually happened; rubber-stamp books hurt in diligence.", f"Director duties in {matter_phrase} contexts are explained in plain language before votes."],
            [f"Expert retainers for {matter_phrase} define assumptions, data access, and report format — otherwise experts run open-ended.", f"We challenge expert scope on {matter_phrase} early; late objections look tactical."],
            [f"Closing a file on {matter_phrase} includes retention policy, destruction dates, and what the client keeps.", f"After {matter_phrase} resolves, we archive privileged material separately from non-privileged business records."],
        ],
    }
    _body_default = [
        [f"For {tlow}, most teams overreact to the latest headline and underreact to the underlying constraint.", f"The question to ask on {tlow}: is the bottleneck people, tooling, process, or timing?"],
        [f"A 30-minute checklist for {tlow}: list the top five failure modes, assign an owner and a date to each.", f"Then decide what evidence you will accept as done on {tlow}."],
        [f"Replace vague goals with numbers when planning {tlow}.", f"A clear definition of done for {tlow} survives busy weeks better than a paragraph of aspirations."],
        [f"Version-controlled decision logs for {tlow} survive staff turnover better than email threads.", f"Post-mortems on {tlow} identify systemic fixes, not blame -- that stops repeat failures."],
        [f"Stakeholder alignment on {tlow} upfront is cheaper than rework from misunderstood requirements.", f"Weekly standups on {tlow} surface blockers when they avoid becoming status-reading sessions."],
        [f"Capacity planning for {tlow} that accounts for interrupts produces more honest timelines.", f"Risk registers on {tlow} reviewed weekly catch dependencies before they become deadline surprises."],
        [f"Documented handoff procedures for {tlow} let new team members contribute in days, not weeks.", f"The people who scope {tlow} stay involved through launch -- no surprise handoff to strangers."],
        [f"Scope documents for {tlow} with measurable outcomes prevent the most common disputes.", f"If the definition of done for {tlow} fits in one sentence, it is probably clear enough."],
        [f"Checklists for {tlow} scale better than tribal knowledge in teams that grow or rotate.", f"Template reuse on {tlow} saves time only when the template was tested on real work, not hypothetical."],
        [f"Retrospectives on {tlow} are short: what broke, what changed, and what we are watching next time.", f"If the same {tlow} issue appears twice, the process -- not the person -- needs fixing."],
        [f"Async updates on {tlow} in a shared doc reduce meeting hours without losing visibility.", f"Dashboards for {tlow} that nobody reads are waste; trim to the three numbers that drive decisions."],
        [f"Dependency mapping for {tlow} before kickoff reveals the sequence that calendars alone miss.", f"The costliest mistake on {tlow} is skipping alignment because the deadline feels urgent."],
    ]

    body_pool = list(_body_pools.get(pack_vid, _body_default))
    rng.shuffle(body_pool)
    block_a, block_b, block_c = body_pool[0], body_pool[1], body_pool[2]

    _closer_pools: dict[str, list[str]] = {
        "cleaning": [
            f"Steady routines outperform reactive fixes. Set an initial cadence for {tlow}, inspect after two cycles, and let the results decide what to tune for {brand_name} clients.",
            f"If {tlow} still feels unclear, the contact page is the fastest way to schedule a walkthrough with {brand_name} in {geo}.",
            f"We update this page when {tlow} procedures change. The date above is the anchor -- if something looks outdated, let us know.",
            f"The goal with {tlow} is not perfection on day one -- it is a reliable baseline that improves after every inspection round.",
            f"Facility managers in {geo} who want specifics on {tlow} should reach out directly; we scope after a walkthrough, not before.",
            f"Most complaints about {tlow} trace back to unclear scope documents. Define surfaces, frequency, and proof of completion before the first shift.",
            f"A building that runs {tlow} well does not look dramatic -- it just never gives tenants a reason to notice.",
            f"Our approach to {tlow} is documented so crews can deliver without guessing. The checklist above reflects what actually happens on site.",
            f"Results from {tlow} improve fastest when supervisors inspect early routes and adjust before habits form.",
            f"Questions about {tlow} in your building? The contact page connects you to {brand_name}'s operations team for a site-specific answer.",
        ],
        "cafe_restaurant": [
            f"Predictable service around {tlow} is designed, not accidental -- {brand_name} publishes these notes so expectations match the experience.",
            f"Open questions about {tlow}? The contact page connects you to the front-of-house team at {brand_name} directly.",
            f"Menus and processes around {tlow} shift seasonally; this page reflects the current setup in {geo}.",
            f"The kitchen at {brand_name} treats {tlow} as a standard, not a suggestion -- every shift follows the same notes.",
            f"Guest feedback on {tlow} directly shapes updates to this page; it is a living document.",
            f"If {tlow} matters to your visit, mentioning it at reservation time gives {brand_name} a head start.",
            f"Service consistency on {tlow} is what separates a good night from a great one -- that is why we document it.",
            f"Questions about {tlow} for private events should go to the events team, not the general contact form.",
            f"The notes on {tlow} above reflect how {brand_name} runs service in {geo} today -- not aspirations.",
            f"We wrote this on {tlow} because informed guests have better experiences, and better experiences bring people back.",
        ],
        "clothing": [
            f"Precision over poetry on {tlow} -- fit and care notes are part of the product at {brand_name}.",
            f"Clarification on {tlow}? The contact page is the fastest path to the {brand_name} support team.",
            f"Measurements and care for {tlow} are tested before publication; the numbers reflect post-wash dimensions.",
            f"The sizing notes on {tlow} above are updated with every production run -- check the date for currency.",
            f"If {tlow} does not meet expectations, the return process is outlined above and support responds within a day.",
            f"We document {tlow} in detail because returns cost everyone time -- accurate information prevents them.",
            f"Customer feedback on {tlow} drives updates to this page; the care notes above reflect real-world use.",
            f"Ordering {tlow} with confidence starts with the measurement guide -- take five minutes before checkout.",
            f"The {tlow} details on this page represent the current production; archived versions are removed to avoid confusion.",
            f"Questions about {tlow} fabric, fit, or returns go through the contact page -- expect a reply within one business day.",
        ],
        "fitness": [
            f"Repeatable habits on {tlow} produce results -- not random intensity. That is how {brand_name} programs.",
            f"Questions about {tlow}? The coaching team at {brand_name} can walk you through it during any session.",
            f"Programming for {tlow} evolves block to block; this page tracks the current approach.",
            f"The notes on {tlow} above reflect how {brand_name} coaches it today in {geo} -- adjustments happen every block.",
            f"If {tlow} is new to you, a single introductory session with a coach covers more than this page can.",
            f"Consistency on {tlow} over months matters more than perfection in any single session -- start and stay.",
            f"Member feedback on {tlow} directly shapes how we program the next training block.",
            f"Recovery between {tlow} sessions is where adaptation happens; the programming above accounts for it.",
            f"Whether {tlow} is your focus or a complement to other training, the scaling options above apply.",
            f"We document {tlow} so members and coaches reference the same standard -- questions go to any coach on the floor.",
        ],
        "marketing_agency": [
            f"Measurable changes on {tlow}, not decks -- {brand_name} tracks everything in a shared changelog.",
            f"If {tlow} is on your radar, the discovery call is the next step -- reach out through the contact page.",
            f"Frameworks for {tlow} adapt to the client; this page describes the default process, not a rigid rulebook.",
            f"The {tlow} playbook above is reviewed quarterly; the process described matches what {brand_name} runs today.",
            f"Results from {tlow} compound -- the first quarter builds infrastructure, the second shows returns.",
            f"Client access and stakeholder alignment on {tlow} are the two factors that most affect timeline accuracy.",
            f"We document {tlow} transparently because agencies that hide process usually hide problems too.",
            f"If {tlow} overlaps with work from other vendors, coordination is handled in a shared project doc.",
            f"Questions about {tlow} scope, timeline, or deliverables go through the contact page -- expect a reply within a day.",
            f"The notes above on {tlow} apply to standard engagements in {geo}; enterprise scopes are customized.",
        ],
        "accounting": [
            f"Solid books make {matter_phrase} cheaper to defend — {brand_name} would rather fix processes early than argue after CRA asks questions.",
            f"If {matter_phrase} still feels unclear, the contact page is the fastest way to book time with {brand_name} in {geo}.",
            f"We revise this page when rules affecting {matter_phrase} shift; the publish date tells you how fresh the guidance is.",
            f"Use these notes on {matter_phrase} alongside your internal controls — software alone does not replace review and sign-off.",
            f"Clients who stay ahead on {matter_phrase} send source documents monthly; year-end surprises are usually a cadence problem.",
            f"The goal on {matter_phrase} is filing positions you can explain — not aggressive numbers that collapse under scrutiny.",
            f"{brand_name} keeps workpapers on {matter_phrase} consistent so any reviewer sees the same story you do.",
            f"When {matter_phrase} touches payroll, sales tax, and income tax, one thread wins — split inboxes create missed deadlines.",
            f"Reach out on {matter_phrase} before you commit to a transaction structure; recharacterizing later is expensive.",
            f"We wrote this on {matter_phrase} so clients in {geo} share vocabulary with our team before the clock is loud.",
        ],
        "legal": [
            f"Good outcomes on {matter_phrase} are usually quiet — clear instructions, disciplined documents, and timelines that match facts.",
            f"If {matter_phrase} needs a tailored strategy, {brand_name} in {geo} scopes after intake — this page is orientation, not a retainer.",
            f"We update guidance on {matter_phrase} when rules or courts move; check the date before you rely on it internally.",
            f"For {matter_phrase}, early written risk calls beat optimistic verbal updates — everyone should read the same paragraph.",
            f"Clients who succeed on {matter_phrase} preserve email and versions; the story matters as much as the law.",
            f"When {matter_phrase} intersects regulators, assume calendars are real — extensions are rarer than people hope.",
            f"{brand_name} prefers narrow fact patterns on {matter_phrase} over sweeping claims that age poorly.",
            f"Questions this page does not answer about {matter_phrase} belong in a confidential consult, not a public comment thread.",
            f"Use these notes on {matter_phrase} to align executives and counsel before spend accelerates — alignment is cheaper than rework.",
            f"We publish on {matter_phrase} so clients in {geo} know how we think before they sign.",
        ],
    }
    _closer_default = [
        f"Good outcomes on {tlow} look boring in the middle. Keep sources linked, revisit after the next cycle, and adjust.",
        f"If {tlow} is still unclear after reading this, the contact page is the fastest way to get specifics from {brand_name}.",
        f"We update this page on {tlow} when practice changes. If something looks outdated, let us know.",
        f"The notes on {tlow} above reflect current practice at {brand_name} -- not aspirations or outdated methods.",
        f"Questions about {tlow} that this page does not answer go through the contact form; we respond within a day.",
        f"Implementation of {tlow} varies by team size and constraints -- use this as a baseline, then adapt.",
        f"We documented {tlow} to save everyone the same explanation in meetings; the page is the standing reference.",
        f"Feedback on {tlow} from clients and staff shapes updates to this page; it is revised periodically.",
        f"Start with the first section on {tlow} and work through it -- the order is intentional.",
        f"The {tlow} process above works at {brand_name} in {geo}; your context may require small adjustments.",
    ]
    closer = rng.choice(_closer_pools.get(pack_vid, _closer_default))

    sections: list[dict[str, Any]] = [
        {"heading": "", "paragraphs_html": [f"<p>{escape(lede)}</p>", f"<p>{p2}</p>", f"<p>{escape(p3)}</p>"]},
        {"heading": h1, "paragraphs_html": [f"<p>{escape(x)}</p>" for x in block_a]},
        {"heading": h2, "paragraphs_html": [f"<p>{escape(x)}</p>" for x in block_b]},
        {"heading": h3, "paragraphs_html": [f"<p>{escape(x)}</p>" for x in block_c]},
        {"heading": rng.choice(
            [
                "Where this leaves you",
                "Next steps",
                "Wrapping up",
                "Key takeaways",
                "Final notes",
                "Summary",
            ]
            if pack_vid in ("legal", "accounting")
            else [
                f"Where {tlow} leaves you",
                f"Next steps on {tlow}",
                f"Wrapping up on {tlow}",
                f"Summary of {tlow}",
                f"The short version of {tlow}",
                f"Key takeaways on {tlow}",
                f"What to do about {tlow}",
                f"Final notes on {tlow}",
            ],
        ), "paragraphs_html": [f"<p>{escape(closer)}</p>"]},
    ]

    mid = sections[1:-1]
    rng.shuffle(mid)
    return [sections[0], *mid, sections[-1]]


def _trim_sections_to_word_budget(sections: list[dict[str, Any]], max_words: int) -> list[dict[str, Any]]:
    """Drop trailing body paragraphs until rough word count fits short-post targets."""
    out = copy.deepcopy(sections)
    guard = 0
    while _approx_words_in_sections(out) > max_words and guard < 500:
        guard += 1
        trimmed = False
        for sec in reversed(out):
            paras = sec.get("paragraphs_html")
            if not isinstance(paras, list) or not paras:
                continue
            last = paras[-1]
            if not isinstance(last, str):
                paras.pop()
                trimmed = True
                break
            if any(tag in last for tag in ("<ol>", "<ul>", "<table", "<dl>", "<blockquote")):
                break
            paras.pop()
            trimmed = True
            break
        if not trimmed:
            break
    return out


def _inject_blog_post_structure(
    sections: list[dict[str, Any]],
    post_type: str,
    rng: random.Random,
    *,
    title: str,
    brand_name: str,
    activity: str,
    city: str,
    country: str,
    vertical_id: str = "",
) -> list[dict[str, Any]]:
    """Insert a structured block (steps, table, FAQ, etc.) before the closing section."""
    if len(sections) < 2:
        return sections
    vinj = (vertical_id or "").strip()
    if vinj in ("legal", "accounting", "consulting"):
        tlow = _blog_topic_for_templates(title, activity=activity)
        if len(tlow) > 42:
            tlow = "this topic"
    else:
        tlow = (title or "").lower().strip()
    geo = ", ".join(x for x in [(city or "").strip(), (country or "").strip()] if x) or "your area"
    act = (activity or "this work").strip()
    extra: dict[str, Any] | None = None

    if post_type in ("how_to", "checklist"):
        headings = [
            f"Ordered steps teams use for {tlow}",
            f"A practical sequence for {tlow}",
            f"How {brand_name} runs {tlow} on site",
        ]
        n = rng.randint(5, 8)
        templates = [
            "Confirm scope, access windows, and the single approver before any work begins.",
            "Document the baseline with photos or measurements so progress is verifiable later.",
            "Stage tools and safety items first; starting mid-flow is when shortcuts appear.",
            "Execute against the checklist, not memory — deviations get noted with a reason.",
            "Verify outcomes against the agreed definition of done before requesting sign-off.",
            "Capture handoff notes for the next visit so context does not reset to zero.",
            "Schedule the follow-up audit while details are fresh, not after complaints arrive.",
            "File paperwork in the format your team already searches for — novelty slows adoption.",
        ]
        rng.shuffle(templates)
        lines = ["<ol>"]
        for j in range(n):
            lines.append(f"<li>{escape(templates[j % len(templates)])}</li>")
        lines.append("</ol>")
        extra = {"heading": rng.choice(headings), "paragraphs_html": ["".join(lines)]}

    elif post_type == "comparison":
        extra = {
            "heading": rng.choice(
                [
                    f"Options teams weigh for {tlow}",
                    f"Trade-offs that show up in {tlow}",
                    f"How {brand_name} compares approaches to {tlow}",
                ],
            ),
            "paragraphs_html": [
                "<table><thead><tr><th>Approach</th><th>Best when</th><th>Tradeoff</th></tr></thead><tbody>"
                f"<tr><td>{escape('Standard playbook')}</td><td>{escape(f'Most {act} scopes in {geo}')}</td>"
                f"<td>{escape('Less flexibility for one-off exceptions')}</td></tr>"
                f"<tr><td>{escape('Custom sprint')}</td><td>{escape('Tight timeline with a named owner')}</td>"
                f"<td>{escape('Higher coordination load week to week')}</td></tr>"
                f"<tr><td>{escape('Phased rollout')}</td><td>{escape('Multi-site or staged budgets')}</td>"
                f"<td>{escape('Slower initial wins, calmer operations')}</td></tr>"
                "</tbody></table>",
            ],
        }

    elif post_type in ("tips", "mistakes", "guide", "industry_update"):
        pairs = [
            (
                f"What changes seasonally around {tlow}?",
                f"In {geo}, weather, traffic, and staffing spikes shift timing more than people expect.",
            ),
            (
                f"What is the fastest way to waste time on {tlow}?",
                "Skipping a written scope and rebuilding decisions in chat threads each week.",
            ),
            (
                f"When should you escalate {tlow}?",
                "When the same failure mode appears twice — that points to a process gap, not a one-off.",
            ),
            (
                f"What do clients underestimate about {tlow}?",
                f"Lead time for access and approvals in {geo} — calendars move faster than building rules allow.",
            ),
        ]
        rng.shuffle(pairs)
        take = rng.choice([3, 4, 5])
        dl = ["<dl>"]
        for q, a in pairs[:take]:
            dl.append(f"<dt>{escape(q)}</dt><dd>{escape(a)}</dd>")
        dl.append("</dl>")
        extra = {
            "heading": rng.choice(
                [
                    f"FAQ-style notes on {tlow}",
                    f"Quick answers readers ask about {tlow}",
                    f"Plain-language Q and A on {tlow}",
                ],
            ),
            "paragraphs_html": ["".join(dl)],
        }

    elif post_type == "case_study":
        extra = {
            "heading": rng.choice(["Timeline highlights", "What happened, in order", "Milestones worth noting"]),
            "paragraphs_html": [
                "<ul>"
                f"<li>{escape(f'Week 1–2: baseline audit for {tlow} with access windows agreed in {geo}.')}</li>"
                f"<li>{escape('Week 3–5: execution window with daily checkpoints against scope.')}</li>"
                f"<li>{escape('Week 6: verification pass, documentation pack, and read-out to stakeholders.')}</li>"
                "</ul>",
            ],
        }
    elif post_type == "interview":
        extra = {
            "heading": "Conversation excerpt",
            "paragraphs_html": [
                "<blockquote><p>"
                f"{escape(f'We bias toward boring, repeatable cadence for {tlow} — excitement in operations is usually a warning sign.')}"
                "</p>"
                f"<cite>— {escape(brand_name)} lead</cite></blockquote>"
                "<blockquote><p>"
                f"{escape(f'Clients in {geo} get clearest results when one owner stays paired with us end-to-end.')}"
                "</p>"
                f"<cite>— {escape(brand_name)} operations</cite></blockquote>",
            ],
        }
    elif post_type == "company_news":
        extra = {
            "heading": rng.choice(["At a glance", "Update summary", "Headline details"]),
            "paragraphs_html": [
                "<ul>"
                f"<li>{escape(f'{brand_name} expanded crew scheduling capacity for {act} routes in {geo}.')}</li>"
                f"<li>{escape(f'Internal training hours on {tlow} increased this quarter to keep quality consistent.')}</li>"
                f"<li>{escape('Customers see the same checklist-backed process; only staffing capacity changed.')}</li>"
                "</ul>",
            ],
        }

    if extra is None:
        return sections
    return sections[:-1] + [extra] + [sections[-1]]


def _approx_words_in_sections(sections: list[dict[str, Any]]) -> int:
    words = 0
    for sec in sections:
        paras = sec.get("paragraphs_html") or []
        if not isinstance(paras, list):
            continue
        for ph in paras:
            if not isinstance(ph, str):
                continue
            # rough: strip tags by splitting on '>'
            textish = ph.replace("<", " ").replace(">", " ")
            words += len(textish.split())
    return words


def _assign_blog_variety(
    posts: list[dict[str, Any]],
    rng: random.Random,
) -> None:
    types = [
        "how_to",
        "case_study",
        "comparison",
        "company_news",
        "guide",
        "checklist",
        "interview",
        "industry_update",
        "mistakes",
        "tips",
    ]
    rng.shuffle(types)
    anc_map = {str(p.get("anchor")): p for p in posts if isinstance(p, dict) and p.get("anchor")}
    all_a = list(anc_map.keys())
    for i, p in enumerate(posts):
        if not isinstance(p, dict):
            continue
        if not str(p.get("post_type") or "").strip():
            p["post_type"] = types[i % len(types)]
        others = [x for x in all_a if x != p.get("anchor")]
        rng.shuffle(others)
        rel: list[dict[str, str]] = []
        for a in others[:3]:
            op = anc_map.get(a)
            if op:
                rel.append({"title": str(op.get("title") or "Post"), "anchor": a})
        p["related_posts"] = rel
        secs = p.get("article_sections_html")
        if not isinstance(secs, list) or not secs:
            continue
        first = secs[0]
        if not isinstance(first, dict):
            continue
        paras = first.get("paragraphs_html")
        if not isinstance(paras, list) or not paras:
            continue
        if rng.random() < 0.72:
            idx = rng.randrange(len(paras))
            ph = paras[idx]
            if isinstance(ph, str) and ph.startswith("<p>") and "</p>" in ph:
                frag = rng.choice(
                    [
                        ' <a href="services.php">See how this maps to our services</a>',
                        ' <a href="faq.php">Read related FAQs</a>',
                        ' <a href="contact.php">Talk to our team</a>',
                    ]
                )
                paras[idx] = ph.replace("</p>", f"{frag}</p>", 1)


def enrich_longform_blog_for_non_news(merged: dict[str, Any], brand: dict[str, Any], rng: random.Random) -> None:
    """Attach long-form posts, authors, categories, trending lists for non-news verticals."""
    vid = str(merged.get("vertical_id") or "").strip()
    if vid == "news":
        return

    brand_name = str(brand.get("brand_name") or "Site")
    city = str(brand.get("city") or "").strip()
    country = str(brand.get("country") or "").strip()
    activity = str(merged.get("activity_summary") or merged.get("industry") or "your work").strip()

    team_items = merged.get("team_items")
    authors = build_blog_authors(
        rng,
        brand_name,
        vid,
        team_items=team_items if isinstance(team_items, list) else None,
        brand=brand,
    )
    merged["blog_authors"] = authors
    cats = _longform_blog_categories(vid)
    merged["blog_categories"] = cats

    blog_mode = str(brand.get("blog_mode") or merged.get("blog_mode") or "full").strip().lower()
    spotlight = blog_mode == "spotlight"
    if spotlight:
        try:
            raw_spot = int(brand.get("blog_spotlight_count", 5))
        except (TypeError, ValueError):
            raw_spot = 5
        n_posts = max(4, min(raw_spot, 10))
    elif vid == "cafe_restaurant":
        n_posts = rng.randint(5, 8)
    elif vid == "cleaning":
        n_posts = rng.randint(9, 13)
    elif vid == "legal":
        n_posts = rng.randint(6, 11)
    elif vid == "pest_control":
        n_posts = rng.randint(7, 11)
    else:
        n_posts = rng.choice([15, 16, 18, 20, 22, 24, 25])
    _span_days = 0
    if vid == "cleaning":
        _span_days = 540
    elif vid == "legal":
        _span_days = 620
    elif vid == "pest_control":
        _span_days = 520
    dates = past_dates_spread(
        rng,
        n_posts,
        brand=brand,
        min_span_days=_span_days,
    )

    if vid == "clothing":
        title_seeds = [
            "How to use our size chart (without guessing)",
            "Fabric notes: what the composition means in wear",
            "Care guide: keep color and shape after wash",
            "Capsule styling: 3 pieces, 5 outfits",
            "Fit notes: how we photograph drape vs. structure",
            "Returns made simple: what to do first",
            "Shipping cutoffs: when labels really scan",
            "Quality checks before a drop ships",
            "What changed from last season (and why)",
            "Bundles vs. single pieces: how to choose",
            "How to measure a garment you already love",
            "Seasonal layering: build outfits that work",
            "Hemming, tailoring, and when it’s worth it",
            "Gift sizing: how to reduce misses",
            "Dyes and finishes: what to expect over time",
            "Sustainability notes we can actually verify",
        ]
    elif vid == "cafe_restaurant":
        title_seeds = [
            "What’s on the menu this month",
            "Seasonal ingredients: planning without drama",
            "Reservations, walk-ins, and the bar",
            "How long a table is yours",
            "Kitchen prep that keeps service smooth",
            "Dietary notes and allergens — kitchen workflow",
            "Wine and non-alc pairings that work",
            "Behind the pass on a busy night",
            "Designing a tasting menu — pacing and arc",
            "What changes between lunch and dinner service",
            "Private events: what to expect before you book",
            "Our approach to tipping and service charges",
            "The one sauce we batch every Sunday",
            "Interview: the sous chef on pacing a Friday service",
            "Why we stopped serving that popular dish",
            "A bread recipe we stole (with permission)",
            "Fermentation corner: what’s in the jars this month",
            "How we write a wine note guests actually read",
            "Brunch vs dinner: two teams, one pass",
            "Suppliers we’ve kept for five years — and why",
        ]
    elif vid == "fitness":
        title_seeds = [
            "How to read our class schedule",
            "Trial visits: what to expect on day one",
            "Strength days vs conditioning days",
            "Deload weeks and why they matter",
            "Class caps — coaching quality vs. packed room",
            "Open gym etiquette during peak hours",
            "How to pick a membership that fits your week",
            "Warm-up blocks coaches actually use",
            "Recovery basics for regular training",
            "What to track besides the scale",
        ]
    elif vid == "cleaning":
        title_seeds = [
            "Routes around your hours — the real constraints",
            "High-touch surfaces: what counts",
            "Move-in / move-out: checklist that matches leases",
            "Photo logs when a spot audit lands",
            "Green chemistry: standardize vs. custom",
            "Documenting chemistry per surface type",
            "Before deep clean: what speeds the first hour",
            "Floor care cadence vs. foot traffic",
            "Color-coded microfiber — why it matters",
            "SDS binders: where auditors look first",
            "Burnishing: traffic-based, not calendar fantasy",
            "Wet-floor signs — timing that holds up in court",
            "Night routes that clear before unlock",
            "Holiday blackouts without surprise no-shows",
            "Restrooms that survive pop-up inspections",
            "Carpet extraction: frequency and spotting",
            "Stone vs. epoxy: different rules, same crew",
            "Keeping route scope from quietly growing",
            "Tenant comms when work gets loud",
            "Elevator and stairwell rotation that sticks",
            "Glass cycles without streak drama",
            "Odor control without perfume cover",
            "Post-construction: dust that comes back if you rush",
            "First week in a new building — what we standardize",
            "Tuesday morning surprise walkthrough — playbook",
            "Why one lobby always runs long",
        ]
    elif vid == "marketing_agency":
        title_seeds = [
            "Week one of an audit: what we ask for first",
            "Pre-launch checks for schema and CWV",
            "Picking metrics for the quarter — sanity filters",
            "Discovery calls that end with a next step",
            "Decision logs that survive Slack churn",
            "Roadmaps vs backlogs: where truth lives",
            "Keeping content and dev on the same ticket",
            "Reports your finance lead won’t glaze over",
            "Technical SEO fixes: impact order, not ego order",
            "When pausing a campaign is the right move",
            "Earned links vs. directory noise",
            "Landing tests that flipped our assumptions",
            "Timelines that don’t assume perfect clients",
            "Keyword research past volume and difficulty",
            "Onboarding: access we need before week two",
            "Quarterly reviews — agenda we actually stick to",
            "Scope changes mid-flight: the one-page rule",
            "Analytics that survives team turnover",
            "Content refresh: triggers, not vibes",
            "CWV wins we could prove in Search Console",
            "Schema: what we ship and what we skip",
            "Everything’s on fire — still need a stack rank",
            "CRO experiments worth running before redesign",
            "Staging and QA before green deploys",
            "Attribution models we like — and avoid",
            "Quick read: three signals your crawl budget is fine",
            "Case note: when staging tags saved a launch",
        ]
    elif vid == "accounting":
        title_seeds = [
            "GST and HST: when registration actually matters",
            "Corporate tax instalments: avoiding CRA interest surprises",
            "T4 and T5 season: what we need from you and when",
            "Bookkeeping cadence that survives an audit",
            "Payroll remittances: PD7A due dates and common slips",
            "Year-end accruals your accountant can defend",
            "Shareholder loans: CRA hot buttons we document early",
            "Motor vehicle logs: what passes a reasonable review",
            "Home office claims: supportable vs. optimistic",
            "T2 filing timeline and Alberta corporate nuances",
            "Sales tax on digital services: a practical checklist",
            "Reconciling Stripe or Square to your GL",
            "Inventory counts that do not wreck December",
            "Contractor vs. employee: paperwork we see missed",
            "Trust accounting basics for property managers",
            "Non-profit restricted funds: statements boards can read",
            "Job costing for trades: WIP and holdbacks",
            "Dividends vs. salary: what we model before year-end",
            "CRA correspondence: how we respond without panic",
            "Record retention: what to keep seven years vs. longer",
            "First consultation: documents that speed intake",
            "Month-end close: reconciliations and review notes",
        ]
    elif vid == "legal":
        title_seeds = [
            "What to bring to a first consultation",
            "How we structure fees, milestones, and billing",
            "Reading a retainer or scope letter without missing exclusions",
            "Confidentiality, conflicts, and intake basics",
            "How we set realistic timelines before you commit",
            "What ‘done’ looks like on a typical matter",
            "When to escalate vs. when to wait for a draft",
            "Document retention: what we keep and why",
            "How we handle scope changes mid-matter",
            "Preparing materials so review cycles stay short",
            "Second opinions and when they make sense",
            "How we communicate bad news early",
            "Checklists we use before filings or submissions",
            "What clients misunderstand about risk and outcomes",
            "How we coordinate with your in-house team",
            "After the matter: what you should file away",
            "How we run discovery without burning the budget",
            "Red flags we watch for in contracts",
            "How we document advice you can rely on later",
            "What a productive check-in looks like",
            "How we prioritize when everything feels urgent",
            "When we recommend outside specialists",
            "How we close a file cleanly",
        ]
    elif vid == "consulting":
        title_seeds = [
            "What to bring to a first consultation",
            "How we structure fees, milestones, and billing",
            "Reading a scope letter without missing the exclusions",
            "How we set realistic timelines before you commit",
            "What ‘done’ looks like on a typical engagement",
            "When to escalate vs. when to wait for a deliverable",
            "Document retention: what we keep and why",
            "How we handle scope changes mid-project",
            "Preparing materials so review cycles stay short",
            "How we run discovery without burning the budget",
            "Red flags we watch for in vendor contracts",
            "How we document decisions you can rely on later",
            "What a productive check-in looks like",
            "How we prioritize when everything feels urgent",
            "When we recommend outside specialists",
            "How we close an engagement cleanly",
        ]
    elif vid in ("dental", "medical"):
        title_seeds = [
            "What happens at a first visit",
            "How we explain treatment options without pressure",
            "Insurance questions we hear most often",
            "How scheduling works for follow-ups",
            "Preparing for a procedure: the short checklist",
            "How we handle pain management and aftercare",
            "Records, privacy, and how information is shared",
            "When to call the office vs. when to wait",
            "How we sterilize and track instruments",
            "What to bring to appointments",
            "How we coordinate with specialists",
            "Kids’ visits: how we pace the appointment",
            "How reminders and confirmations work",
            "What emergency access looks like",
            "How we document treatment plans",
            "Medications and allergies: why we ask every time",
            "How we handle billing questions",
            "What to expect after a routine cleaning or checkup",
            "How we train staff on bedside manner",
            "Seasonal health notes we share with patients",
        ]
    elif vid == "real_estate":
        title_seeds = [
            "How showings are scheduled and confirmed",
            "What to expect before your first offer",
            "Reading disclosures without missing the footnotes",
            "How we price against recent comps",
            "Inspection day: who should attend",
            "What earnest money protects (and what it doesn’t)",
            "How we handle multiple-offer situations",
            "Closing timeline: the milestones in order",
            "Rentals vs. purchases: how we advise differently",
            "How we market a listing in the first two weeks",
            "Open houses: goals, safety, and follow-up",
            "How we negotiate repair credits vs. fixes",
            "Title issues and when to pause",
            "What movers need from you before closing",
            "How we communicate with lenders and attorneys",
            "New construction: upgrades vs. allowances",
            "How we handle lease renewals",
            "Staging: when it pays off and when it doesn’t",
            "How we vet buyers before serious paperwork",
            "What happens if a deal falls through",
        ]
    elif vid == "news":
        title_seeds = [
            "How we label analysis vs. reporting",
            "Corrections: how we surface fixes",
            "How we verify tips before publication",
            "What ‘on the record’ means in our newsroom",
            "How we handle graphic or sensitive material",
            "Elections coverage: what we won’t speculate on",
            "How we work with freelance contributors",
            "What goes into a morning brief",
            "How we cite data and studies",
            "When we delay a story for safety",
            "How reader feedback reaches editors",
            "Syndication and republishing rules",
            "How we archive updated stories",
            "Conflict of interest disclosures",
            "How we cover ongoing investigations",
            "What our ethics policy leaves out (on purpose)",
            "How we choose what not to cover",
            "Podcasts and newsletters: how they differ from the site",
            "How we train junior reporters on sourcing",
            "When we add context notes mid-crisis",
        ]
    elif vid == "pest_control":
        title_seeds = [
            "When ants move indoors after a warm snap",
            "Commercial kitchens: where roach pressure starts",
            "Rodent noise in walls — confirming without demo",
            "Swarmers outside: termites vs. ants at a glance",
            "Bed bugs after travel — what to inspect first",
            "Exclusion that survives the next freeze-thaw cycle",
            "IPM paperwork food auditors actually read",
            "Perimeter work and pets — how we schedule visits",
            "Multi-unit notices, re-entry, and shared walls",
            "Moisture pockets that invite springtails",
            "Stinging insects: remove, relocate, or monitor",
            "Pantry moths and bulk storage hygiene",
            "Spider pressure at thresholds and soffits",
            "Drain flies when the fix is not more spray",
            "Garage gaps rodents squeeze through",
            "New builds: treatment timing vs. move-in",
            "Tenant turnover: what we verify before the next lease",
            "Health inspection prep — logs and placements",
            "Loading docks where pest pressure follows pallets",
            "Seasonal wasp activity around eaves",
            "Subterranean termite tubes: when to act fast",
            "Attic squirrels — humane timing and follow-up",
            "Bird nesting in signage: options by species",
        ]
    elif vid in _TRADES_VERTICALS:
        title_seeds = [
            "What the first hour on site is actually for",
            "Written estimates: line items that prevent sticker shock",
            "After-hours calls: how priority and pricing are set",
            "Permits and inspections: who schedules and who attends",
            "Protecting finishes while work is in progress",
            "Warranty vs. wear: how we document the difference",
            "Maintenance most people defer until failure",
            "Photo baselines before we change equipment",
            "Van stock that looks random until you see the route",
            "Work staged across days without losing continuity",
            "Bringing in specialists: how handoffs stay clean",
            "Start-of-day checks before tools go loud",
            "Add-ons: how scope and price move together",
            "Site prep: what has to be clear for safe access",
            "Finishing checks before we sign the job closed",
            "Training newer crew without slowing the paying visit",
            "Comfort upgrades: where early numbers help decisions",
            "Older structures: what we assume is behind the finish",
            "Closeout docs that match what carriers ask for",
            "End-of-week scheduling: why slots tighten",
            "Same symptom on repeat visits: the usual story",
            "Route days when the second stop changes the first",
        ]
    else:
        title_seeds = [
            "Before kickoff: the five emails we wish arrived earlier",
            "Checklist that actually prevents rework",
            "Measuring progress without vanity charts",
            "The trade-off nobody says out loud in planning",
            "Scope changes — one template, fewer fights",
            "When stakeholders disagree: who decides first",
            "Timeline slips: usual suspects",
            "Decision logs that outlive Slack threads",
            "Quality in practice — not the poster version",
            "Constraints, capacity, and saying no politely",
            "Reviews that don’t stall shipping",
            "Small ops habits that compound quietly",
            "Standardize vs. customize — quick test",
            "Tools we adopt — and ones we ignore on purpose",
            "Quarter in review — compressed",
            "Audit this before the next cycle",
            "Keeping multi-team projects one thread",
            "After the last incident: what we changed",
            "Boring workflow on purpose",
            "Edge cases without fire drills",
            "When to reopen the plan",
            "Field note: the week the board went sideways",
            "Why that checklist exists",
            "If we started today — one thing we’d do sooner",
            "Quick read: three signs you’re over-meeting",
            "Same problem, three teams — how we untangle it",
        ]
    ident_blog = str(brand.get("generation_identity") or merged.get("generation_identity") or brand_name).strip()
    dom_blog = str(brand.get("domain") or "").strip()
    blog_seed = int(
        hashlib.sha256(f"blog|{ident_blog}|{dom_blog}|{vid}|{brand_name}|{city}".encode("utf-8")).hexdigest(),
        16,
    ) % (2**32)
    blog_rng = random.Random(blog_seed)
    blog_rng.shuffle(title_seeds)

    def _build_dek(rr: random.Random, *, title: str, category: str, register: str = "neutral") -> str:
        geo = f"{city}" if city else (country or "your area")
        t = title.strip()
        cat = category.strip()
        pools: dict[str, list[str]] = {
            "cleaning": [
                f"{t}: what we check on a real route in {geo}, plus the checklist we use.",
                f"A practical {cat.lower()} note from the {brand_name} team in {geo}: {t}.",
                f"{t} — surface-first steps, not generic advice (with sources and what to do next).",
            ],
            "clothing": [
                f"{t} — sizing, fabric behavior, and what to measure before you order in {geo}.",
                f"A short {cat.lower()} guide from {brand_name}: {t}, with care notes and pitfalls.",
                f"{t}: practical fit and care notes, plus when to return vs tailor.",
            ],
            "cafe_restaurant": [
                f"{t} — what changes seasonally, what stays stable, and how to plan around it in {geo}.",
                f"A {cat.lower()} note from {brand_name}: {t}, with what to expect when it’s busy.",
                f"{t}: practical guest-facing detail (timing, allergies, pacing) from {geo}.",
            ],
            "fitness": [
                f"{t} — how we coach it on the floor in {geo}, and what to track week to week.",
                f"A {cat.lower()} note from {brand_name}: {t}, plus the habit that makes it stick.",
                f"{t}: a practical guide to form, pacing, and recovery without overthinking it.",
            ],
            "marketing_agency": [
                f"{t} — the practical checklist we run before we ship changes for clients in {geo}.",
                f"A {cat.lower()} explainer from {brand_name}: {t}, with what we measure (and why).",
                f"{t}: steps, examples, and the two metrics we won’t ship without.",
            ],
            "accounting": [
                f"{t} — GST/HST, payroll, and year-end habits from {brand_name} for readers in {geo}.",
                f"A {cat.lower()} note from {brand_name}: {t}, with reconciliations and CRA-facing documentation.",
                f"{t}: what to gather before month-end, what we file, and what belongs in the workpaper pack.",
            ],
            "legal": [
                f"{t} — how {brand_name} handles intake, risk framing, and timelines for clients in {geo}.",
                f"A {cat.lower()} briefing from {brand_name}: {t}, with what to bring to a first consultation.",
                f"{t}: plain-language practice notes on scope, confidentiality, and what “done” usually looks like.",
            ],
            "consulting": [
                f"{t} — delivery checkpoints from {brand_name} for teams operating in {geo}.",
                f"A {cat.lower()} guide from {brand_name}: {t}, with documentation habits that survive turnover.",
                f"{t}: what we measure, what we refuse to rush, and how we close engagements cleanly.",
            ],
            "generic": [
                f"{t} — a practical {cat.lower()} note from {brand_name} for teams working in {geo}.",
                f"{t}: steps you can reuse, plus the pitfalls that waste the most time.",
                f"{t} — what we’d check first, what we’d measure, and what to do next.",
            ],
        }
        pool = pools.get(vid) or pools["generic"]
        dek = rr.choice(pool).strip()
        if register == "conversational" and rr.random() < 0.44:
            dek = rr.choice(
                [
                    f"{t} — candid notes from {brand_name} in {geo}.",
                    f"About {t}: what we actually run in {geo}, without the deck.",
                    f"{t}? Same questions every month — here’s our standing answer for {geo}.",
                ],
            ).strip()
        elif register == "formal" and rr.random() < 0.36:
            dek = (dek + f" Prepared for stakeholders reviewing work in {geo}.").strip()
        return dek[:300].rstrip()

    def _fill_to_target_words(
        sections_in: list[dict[str, Any]],
        r: random.Random,
        *,
        target_words: int = 880,
        allow_filler: bool = True,
    ) -> list[dict[str, Any]]:
        sections = _dedup_sections_html(sections_in)
        wc = _approx_words_in_sections(sections)
        if target_words <= 520 and wc > int(target_words * 1.28):
            sections = _trim_sections_to_word_budget(sections, int(target_words * 1.12))
            wc = _approx_words_in_sections(sections)
        tl = _blog_topic_for_templates(title, activity=activity)
        fb_vid = "legal" if vid == "consulting" else vid
        if fb_vid in ("hvac", "plumbing", "electrical", "roofing", "landscaping", "auto_repair", "moving"):
            fb_vid = "trades_field"
        if fb_vid in ("legal", "consulting", "accounting") and len(tl) > 40:
            tl = "this topic"
        _filler_banks: dict[str, list[str]] = {
            "clothing": [
                f"Quick fit check for {tl}: measure a similar garment you already own and compare flat measurements before ordering.",
                f"Care tip for {tl}: wash cold, avoid overdrying, and reshape seams while damp so the silhouette stays consistent.",
                f"If you are between sizes on {tl}, decide whether you want drape or structure -- then pick based on the intended fit.",
                f"For returns on {tl}, keep packaging intact and try items indoors so tags stay clean and the process is painless.",
                f"Shipping for {tl}: carrier scans can lag at peak volume; cutoff times are based on handoff, not just label creation.",
                f"Fabric note on {tl}: blends trade softness, stretch, and wrinkle recovery -- composition is a hint, not the whole story.",
                f"Color consistency on {tl} varies between dye lots; we note batch-specific shifts when they occur.",
                f"Layering with {tl} works best when each piece has a defined role: base, mid for insulation, outer for protection.",
                f"For {tl}, hang knits on padded hangers to avoid shoulder dimples, or fold them if drawer space allows.",
                f"Pre-wash shrinkage for {tl} is tested before we publish measurements, so listed dimensions reflect post-wash.",
            ],
            "cleaning": [
                f"For {tl}, run the checklist with photos before and after so quality is visible, not assumed.",
                f"If access is limited during {tl}, plan routes around tenant hours and prioritize high-touch surfaces first.",
                f"Document chemistry choices for {tl} per surface so finishes are not damaged when staff rotates.",
                f"When schedules change on {tl}, update the scope once instead of making one-off exceptions that drift.",
                f"Seasonal deep cleans related to {tl} should be scoped separately; they are not an extension of daily routes.",
                f"Microfiber color coding during {tl} prevents cross-contamination between restrooms, kitchens, and general areas.",
                f"SDS binders for {tl} should be accessible at every supply closet, not just the main office.",
                f"Burnishing and stripping for {tl} depend on traffic volume; default schedules often under-serve lobbies.",
                f"Wet-floor signage for {tl} goes up before the first mop pass, not after.",
                f"Feedback loops on {tl} close faster when supervisors photograph the same angles each visit.",
            ],
            "cafe_restaurant": [
                f"Allergen verification for {tl} happens at prep; the kitchen flags each ticket before plating.",
                f"Pacing for {tl} requires rehearsed transitions between the pass and the floor.",
                f"Wine and non-alcoholic pairings for {tl} are reviewed together so recommendations stay honest.",
                f"Seasonal swaps on {tl} are briefed to servers before the first cover, not after a guest asks.",
                f"Plate temperatures for {tl} are checked at the pass -- timing means nothing if the dish arrives cold.",
                f"Reservation notes for {tl} include party size and dietary constraints so prep is not improvised.",
                f"Tasting menu flow for {tl} follows a flavor arc: lighter first, richer middle, refreshing close.",
                f"Mise en place for {tl} is audited before doors open to prevent mid-rush scrambles.",
                f"Server briefings for {tl} cover specials, modifications, and any items that are 86'd.",
                f"Post-service prep for {tl} the next day starts immediately after close -- that is how consistency scales.",
            ],
            "fitness": [
                f"Form corrections for {tl} happen during the warm-up, not mid-set when fatigue competes with focus.",
                f"Equipment maintenance for {tl} is tracked like membership records -- boring until it prevents an injury.",
                f"Class caps for {tl} exist so coaching quality holds when attendance spikes unexpectedly.",
                f"Trial visitors for {tl} get a movement screen so coaches recommend the right starting point.",
                f"Rest intervals for {tl} matter as much as working sets; they are programmed, not improvised.",
                f"Deload weeks for {tl} are scheduled in advance; they protect joints and keep progress sustainable.",
                f"Gym etiquette during {tl}: strip bars, share racks during peaks, wipe benches after use.",
                f"Progressive overload on {tl} means adding stimulus systematically, not piling on weight each session.",
                f"Recovery protocols after {tl} include sleep, hydration, and active mobility -- not just protein shakes.",
                f"Warm-up quality before {tl} affects performance and injury risk; it is non-negotiable in our programming.",
            ],
            "marketing_agency": [
                f"Staging environments for {tl} stay tagged so you always know what is live versus queued.",
                f"Schema validation for {tl} runs on deploy; broken structured data is caught before indexing.",
                f"Reporting on {tl} defaults to metrics your finance team recognizes, not vanity dashboards.",
                f"Changelog entries for {tl} link rankings and conversions back to specific releases.",
                f"Content briefs for {tl} include intent mapping; the writer needs the page purpose, not a keyword list.",
                f"Backlink audits for {tl} distinguish earned links from directory spam; cleanup happens before outreach.",
                f"Sample sizes for {tl} A/B tests are calculated before launch so results are statistically meaningful.",
                f"Crawl budget allocation for {tl} is checked in technical audits so important pages get indexed promptly.",
                f"Competitor gap analysis for {tl} identifies content opportunities ranked by search volume and difficulty.",
                f"Post-launch monitoring for {tl} runs for 30 days before declaring a change successful or rolling it back.",
            ],
            "accounting": [
                f"For {tl}, tie each GL account to a source register — bank, payroll, or subledger — before tax work starts.",
                f"GST filings on {tl} need supporting spreadsheets; CRA reviewers ask for the bridge from the trial balance to the return.",
                f"Payroll accruals for {tl} should match approved timesheets; estimates without backup rarely survive year-end.",
                f"T5 and dividend resolutions for {tl} belong in the same minute pack; dividends declared in error are painful to unwind.",
                f"Capital vs. expense calls on {tl} should reference dollar thresholds your capitalization policy already names.",
                f"For {tl}, document related-party loans with terms and repayment history — verbal agreements do not age well.",
                f"Sales cut-off for {tl} means matching revenue to shipment or service delivery, not to when cash hits the bank.",
                f"Use {tl} checklists at month-end; waiting until March to discover missing T4 boxes wastes everyone’s time.",
                f"Alberta corporate tax instalments intersect with {tl}; model both provincial and federal calendars together.",
                f"Charity and NPO readers: restricted revenue for {tl} must hit the right fund columns — unrestricted sweeps raise audit flags.",
            ],
            "pest_control": [
                f"Entry-point mapping during {tl} matters more than spray volume; gaps above doors defeat perimeter work.",
                f"Bait stations for {tl} need dated service logs — auditors and landlords ask for them.",
                f"Interior {tl} visits need pet and occupant notes on file before technicians arrive.",
                f"Follow-up windows after {tl} are predictable when customers prep kitchens and storage the same way.",
                f"Exclusion work tied to {tl} should list materials used; warranty calls trace back to that list.",
                f"Multi-unit {tl} routes batch adjacent suites so re-entry rules stay consistent.",
                f"Seasonal ant pressure around {tl} shifts with weather — exterior barriers beat reactive interior-only sprays.",
                f"Documentation photos for {tl} protect both sides when neighbors dispute drift or access.",
                f"IPM plans for {tl} name thresholds before chemical escalation — that language belongs in the contract.",
                f"After-hours {tl} emergencies still need SDS and PPE checks; fatigue is when shortcuts appear.",
            ],
            "trades_field": [
                f"Lockout/tagout before {tl} is non-negotiable; shortcuts show up in incident reports, not invoices.",
                f"Van stock for {tl} should match the top ten failure modes in your market — not a generic parts list.",
                f"Photo the nameplate when {tl} involves equipment; wrong model numbers waste a return trip.",
                f"Customer sign-off on {tl} scope prevents 'while you are here' scope creep that burns the route.",
                f"Weather delays {tl} more than people admit; buffer the second job when the first is outdoors.",
                f"First-hour diagnostics for {tl} should have a checklist — experienced techs still miss one sensor.",
                f"Permit packets for {tl} belong in one folder; split PDFs lose pages at inspection.",
                f"Tool calibration logs for {tl} matter when a warranty vendor asks for proof of proper torque.",
                f"Drain-down and refill steps for {tl} need written volumes; guessing wastes chemistry and time.",
                f"End-of-day photos for {tl} jobs close the loop with dispatch faster than verbal handoffs.",
            ],
            "legal": [
                f"For {tl}, confirm who signs and who is informed — authority gaps cause delays at filing deadlines.",
                f"Version control on {tl} drafts matters; courts and tribunals compare iterations when credibility is questioned.",
                f"On {tl}, privilege logs should be started when productions begin — retroactive logs invite challenges.",
                f"Mediation briefs for {tl} should lead with facts and damages theory; procedural grievances belong in an appendix.",
                f"Regulator correspondence on {tl} needs a single custodian; split inboxes lose attachments and dates.",
                f"Contract playbooks for {tl} should flag indemnity caps and notice windows — boilerplate without review is risky.",
                f"For {tl}, employment releases need consideration and clear scope; template waivers fail when facts shift.",
                f"Estates touching {tl} need capacity notes near the will file — afterthought memos look manufactured.",
                f"Corporate records for {tl} should match board actions; backdated minutes are a diligence nightmare.",
                f"Cross-border {tl} issues need local counsel memos on conflicts and enforcement — assume nothing about reciprocity.",
            ],
        }
        _loc_hint = (city or "").strip() or "our market"
        filler_pool = list(_filler_banks.get(fb_vid, [
            f"Scope documents for {tl} that define done in measurable terms prevent the most common handoff disputes.",
            f"Weekly standups on {tl} surface blockers effectively when they avoid becoming status-reading rituals.",
            f"Version-controlled decision logs for {tl} survive staff turnover better than email threads.",
            f"Post-mortems on {tl} should identify systemic fixes, not assign blame; that stops repeat failures.",
            f"Stakeholder alignment on {tl} is cheaper than rework cycles from misunderstood requirements.",
            f"Checklists for {tl} scale better than tribal knowledge; they prevent repeat mistakes.",
            f"Documented handoff procedures for {tl} let new team members contribute in days instead of weeks.",
            f"Risk registers for {tl} reviewed weekly catch dependencies before they become deadline surprises.",
            f"Capacity planning for {tl} that accounts for interrupts produces more honest timelines.",
            f"Definition of ready for {tl} matters as much as definition of done; unclear inputs yield unclear outputs.",
            f"Same {tl} question hit three inboxes in {_loc_hint} last week — this page is the shortcut.",
            f"Usually {tl} discussions run long when nobody brings the baseline doc; start there.",
            f"Sometimes {tl} is a fifteen-minute fix; sometimes it waits on legal — both happen.",
            f"Rain-day delays aside, {tl} rarely needs a hero; it needs a named owner and a date.",
            f"Quick math: two days of clarify-up-front on {tl} beats two weeks of rework most quarters.",
        ]))
        r.shuffle(filler_pool)
        used: set[str] = set()
        soft_cap = max(int(target_words * 1.38), target_words + 220)
        if allow_filler:
            for filler in filler_pool:
                if wc >= target_words:
                    break
                if wc >= soft_cap:
                    break
                if filler in used:
                    continue
                used.add(filler)
                sections[-1]["paragraphs_html"].append(f"<p>{escape(filler)}</p>")
                wc += len(filler.split())
        sections[-1]["paragraphs_html"] = _dedup_paragraphs_html(sections[-1]["paragraphs_html"])
        return sections

    min_posts = 4 if spotlight else 8
    attempts_per_post = 4
    unique_threshold = 0.8
    max_similarity = 1.0 - unique_threshold

    kept_posts: list[dict[str, Any]] = []
    kept_fps: list[set[str]] = []
    seen_anchors: set[str] = set()
    seen_titles: set[str] = set()

    _post_type_pool = [
        "how_to",
        "case_study",
        "comparison",
        "company_news",
        "guide",
        "checklist",
        "interview",
        "industry_update",
        "mistakes",
        "tips",
    ]
    if vid == "cleaning":
        _post_type_pool = [t for t in _post_type_pool if t != "company_news"] + ["industry_update", "tips"]
    elif vid == "legal":
        _post_type_pool = [t for t in _post_type_pool if t != "company_news"] + ["guide", "checklist", "tips"]
    rng.shuffle(_post_type_pool)
    zones_brand = brand.get("service_area_zones")
    zone_list_blog = (
        [str(z).strip() for z in zones_brand if str(z).strip()] if isinstance(zones_brand, list) else []
    )

    for i in range(n_posts):
        post_type = _post_type_pool[i % len(_post_type_pool)]
        title = str(title_seeds[i % len(title_seeds)]).strip()
        if title.lower() in seen_titles:
            suffixes = ["checklist", "primer", "notes", "update", "field notes", "playbook", "brief", "addendum"]
            for sfx in suffixes:
                candidate = f"{title} ({sfx})"
                if candidate.lower() not in seen_titles:
                    title = candidate
                    break
        tpls = _title_prefix_candidates(post_type, vid)
        if vid == "legal":
            _prefix_p = 0.16
        elif vid in _TRADES_VERTICALS or vid == "pest_control":
            _prefix_p = 0.12
        else:
            _prefix_p = 0.38
        if tpls and rng.random() < _prefix_p:
            title = rng.choice(tpls).replace("{t}", title)
        if vid == "legal":
            lowt = title.lower()
            if "internal note" in lowt or lowt.startswith("signals on "):
                title = title_seeds[i % len(title_seeds)].strip()
        seen_titles.add(title.lower())
        category = rng.choice(cats) if cats else "Updates"
        if spotlight:
            word_target = rng.choice([1400, 1800, 2200])
        elif vid == "legal":
            word_target = rng.choice([360, 480, 620, 780, 940, 1180, 1420, 1680])
        elif vid == "pest_control":
            word_target = rng.choice([380, 520, 680, 850, 1020, 1280, 1580, 1920, 2240])
        else:
            word_target = rng.choice([400, 800, 1200])
        district_pick = ""
        _geo_blog_p = 0.09 if vid == "cleaning" else 0.22
        if zone_list_blog and rng.random() < _geo_blog_p:
            district_pick = rng.choice(zone_list_blog)
        base_anchor = _blog_post_slug_parts(
            title,
            rng=rng,
            city=city,
            district=district_pick,
            post_type=post_type,
            vertical_id=vid,
            site_identity=str(brand.get("generation_identity") or merged.get("generation_identity") or brand_name),
        )
        anchor = _unique_slug_in_set(base_anchor, seen_anchors)
        display_d, iso_d = dates[i]
        sources = _pick_sources_for_post(rng, vid, country, 4)
        author = authors[i % len(authors)] if authors else {"id": "", "name": "", "slug": ""}

        base_post: dict[str, Any] = {
            "title": title,
            "category": category,
            "post_type": post_type,
            "target_words": word_target,
            "anchor": anchor,
            "date": display_d,
            "date_iso": iso_d,
            "author_id": author.get("id") or "",
            "author_name": author.get("name") or "",
            "author_slug": author.get("slug") or "",
            "sources": sources,
            "post_image_src": f"img/posts/{anchor}.jpg",
            "published": True,
        }

        post_register = pick_register_for_blog_post(i, rng)
        chatty = prose_chatty_strength(brand, merged)
        micro_prose = prose_micro_imperfections_enabled(brand, merged)

        chosen: dict[str, Any] | None = None
        for attempt in range(attempts_per_post):
            # Regenerate body sections with a per-attempt deterministic RNG to vary headings/order.
            salt = f"{anchor}|{attempt}|{brand_name}"
            local_seed = int.from_bytes(salt.encode("utf-8"), "little") % (2**32)
            rr = random.Random(local_seed)

            sections = _longform_section_pack(
                rng=rr,
                brand_name=brand_name,
                city=city,
                country=country,
                activity=activity,
                vertical_id=vid,
                title=title,
                category=category,
                sources=sources,
            )
            sections = _inject_blog_post_structure(
                sections,
                post_type,
                rr,
                title=title,
                brand_name=brand_name,
                activity=activity,
                city=city,
                country=country,
                vertical_id=vid,
            )
            sections = _fill_to_target_words(
                sections, rr, target_words=word_target, allow_filler=not spotlight
            )
            if prose_humanize_enabled(brand, merged):
                vary_first_section_plain_shape(sections, rr)
                apply_inject_to_random_html_paragraphs(sections, brand, rr)
                massage_first_html_paragraph(
                    sections,
                    rr,
                    register=post_register,
                    micro=micro_prose,
                    chatty_strength=chatty,
                )
                apply_blog_post_depth_pass(
                    sections,
                    brand,
                    rr,
                    register=post_register,
                    micro=micro_prose,
                    chatty_strength=chatty,
                )
            post = dict(base_post)
            dek = _build_dek(rr, title=title, category=category, register=post_register)
            post["dek"] = dek
            post["excerpt"] = dek[:280] + ("…" if len(dek) > 280 else "")
            post["article_sections_html"] = sections

            fp = _post_fingerprint(post)
            sim = _max_similarity(fp, kept_fps)
            if sim <= max_similarity:
                chosen = post
                break
            # If we are starving for posts, accept a slightly higher similarity rather than ending up with 1 post.
            if len(kept_posts) < min_posts and sim <= 0.25:
                chosen = post
                break

        if chosen is None:
            # Fallback: take last generated version even if similar, but still avoid anchor duplicates.
            chosen = post

        fp_final = _post_fingerprint(chosen)
        kept_posts.append(chosen)
        kept_fps.append(fp_final)
        seen_anchors.add(anchor)

    posts_unique = _dedup_posts_by_anchor(kept_posts)
    # Hard guarantee: if similarity logic somehow collapses, keep first min_posts.
    if len(posts_unique) < min_posts and len(kept_posts) >= min_posts:
        posts_unique = _dedup_posts_by_anchor(kept_posts)[:min_posts]

    posts_visible = [p for p in posts_unique if isinstance(p, dict) and p.get("published", True)]
    merged["blog_posts"] = posts_visible
    merged["blog_page_groups"] = [posts_visible[i : i + 4] for i in range(0, len(posts_visible), 4)]

    merged.setdefault("blog_heading", "Insights & updates")
    if spotlight:
        merged.setdefault(
            "blog_intro",
            f"Long-form articles from {brand_name} — a smaller set of posts, each written to be bookmarked and reused.",
        )
    else:
        merged.setdefault(
            "blog_intro",
            f"Long-form notes from {brand_name} — practical, sourced, and written to be used.",
        )

    trending = [posts_visible[i] for i in rng.sample(range(len(posts_visible)), min(5, len(posts_visible)))]
    popular = [posts_visible[i] for i in rng.sample(range(len(posts_visible)), min(5, len(posts_visible)))]
    merged["trending_posts"] = [
        {"title": p["title"], "anchor": p["anchor"], "category": p["category"]} for p in trending
    ]
    merged["popular_posts"] = [
        {"title": p["title"], "anchor": p["anchor"], "category": p["category"]} for p in popular
    ]
    _assign_blog_variety(posts_visible, rng)

_VERTICAL_SEO_LABEL: dict[str, str] = {
    "cafe_restaurant": "Restaurant",
    "cleaning": "Cleaning services",
    "marketing_agency": "Digital marketing",
    "fitness": "Gym & training",
    "clothing": "Apparel retail",
    "news": "News & briefings",
    "generic": "",
}


def _about_services_link_label(vertical_id: str) -> str:
    return {
        "news": "sections & coverage",
        "cafe_restaurant": "menus & hospitality",
        "cleaning": "programs & quotes",
        "fitness": "membership & classes",
        "clothing": "shop & product care",
        "marketing_agency": "capabilities & pricing",
    }.get(vertical_id.strip(), "services & details")


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_verticals(data_dir: Path) -> list[dict[str, Any]]:
    raw = _load_yaml(data_dir / "verticals.yaml")
    if not isinstance(raw, list):
        return []
    out = [x for x in raw if isinstance(x, dict) and x.get("id")]
    if out:
        return out
    return [_fallback_vertical()]


def _fallback_vertical() -> dict[str, Any]:
    return {
        "id": "generic",
        "label_ru": "Общая",
        "hint": "Универсальные формулировки (нет verticals.yaml или он пуст).",
        "activity_summary": "professional services and client projects",
        "tagline_candidates": ["{brand_name} — clarity, growth, and measurable outcomes."],
        "seo_blurb": "{brand_name} partners with teams on strategy, delivery, and ongoing optimization.",
        "hero_title": "{brand_name} helps teams ship work that lasts",
        "hero_subtitle": "We combine planning and hands-on execution so initiatives reach the finish line with clear milestones.",
        "about_page_header": "About us",
        "about_page_sub": "Background, values, and how we work.",
        "contact_page_header": "Contact",
        "contact_page_sub": "We respond within one business day.",
        "about_heading": "Who we are",
        "about_body": (
            "{brand_name} is a focused team combining strategy and execution for organizations "
            "that need dependable outcomes, not slide decks."
        ),
        "services_heading": "What we do",
        "services_intro": "Engagements center on discovery, delivery, and iteration — with reporting you can act on.",
        "service_items": [
            {"title": "Strategy", "text": "Roadmaps, positioning, and prioritization."},
            {"title": "Delivery", "text": "Hands-on execution with clear milestones."},
            {"title": "Support", "text": "Ongoing optimization and reporting."},
        ],
        "contact_teaser": "Tell us about your project — we reply within one business day.",
    }


def _coerce_vertical_text(x: Any) -> str:
    """YAML can parse 'foo: bar' in a list as a mapping; normalize to one string."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return "; ".join(f"{k}: {v}" for k, v in x.items())
    return str(x)


def pick_vertical(
    rng: random.Random,
    vertical_id: str | None,
    verticals: list[dict[str, Any]],
) -> dict[str, Any]:
    if not verticals:
        return copy.deepcopy(_fallback_vertical())
    want = (vertical_id or "").strip()
    if want:
        for v in verticals:
            if str(v.get("id")) == want:
                return copy.deepcopy(v)
        raise ValueError(f"Unknown vertical: {want!r}. Use a valid id or omit for random selection.")
    return copy.deepcopy(rng.choice(verticals))


# Careers page: titles must match the vertical (no "Field lead" on a law-firm site).
_CAREERS_ROLE_POOLS: dict[str, tuple[str, ...]] = {
    "legal": (
        "Associate lawyer",
        "Paralegal",
        "Legal assistant",
        "Clerk / articling student",
    ),
    "accounting": (
        "Staff accountant",
        "Senior accountant",
        "Bookkeeper",
        "Accounting intern / trainee",
    ),
    "consulting": (
        "Consultant",
        "Senior consultant",
        "Analyst",
        "Associate / graduate hire",
    ),
    "marketing_agency": (
        "SEO / growth specialist",
        "Account manager",
        "Content strategist",
        "Junior marketing coordinator",
    ),
    "news": (
        "Reporter / correspondent",
        "Editor",
        "Producer",
        "Editorial assistant / intern",
    ),
    "cafe_restaurant": (
        "Line cook",
        "Front-of-house supervisor",
        "Sous chef",
        "Prep cook / junior kitchen",
    ),
    "fitness": (
        "Head coach",
        "Membership advisor",
        "Group fitness instructor",
        "Floor staff / junior coach",
    ),
    "clothing": (
        "E-commerce coordinator",
        "Fulfillment lead",
        "Customer support specialist",
        "Retail operations assistant",
    ),
    "dental": (
        "Registered dental hygienist",
        "Dental assistant",
        "Treatment coordinator",
        "Reception / patient care",
    ),
    "medical": (
        "Clinic nurse / MOA",
        "Medical office assistant",
        "Patient coordinator",
        "Administrative assistant",
    ),
    "real_estate": (
        "Sales associate",
        "Showing coordinator",
        "Transaction coordinator",
        "Junior agent / trainee",
    ),
}
_TRADES_CREW_ROLES: tuple[str, ...] = (
    "Field lead",
    "Client coordinator",
    "Operations specialist",
    "Apprentice / trainee",
)


def _careers_role_pool(vertical_id: str) -> tuple[str, ...]:
    v = vertical_id.strip()
    if v in _CAREERS_ROLE_POOLS:
        return _CAREERS_ROLE_POOLS[v]
    if v in _TRADES_VERTICALS or v == "cleaning":
        return _TRADES_CREW_ROLES
    return _CAREERS_ROLE_POOLS["consulting"]


def _careers_copy_family(vertical_id: str) -> str:
    v = vertical_id.strip()
    if v in _CAREERS_ROLE_POOLS:
        if v in {"legal", "accounting", "consulting"}:
            return "office"
        if v == "marketing_agency":
            return "creative"
        if v == "news":
            return "editorial"
        if v == "cafe_restaurant":
            return "hospitality"
        if v == "fitness":
            return "fitness"
        if v == "clothing":
            return "retail"
        if v in {"dental", "medical"}:
            return "healthcare"
        if v == "real_estate":
            return "real_estate"
    if v in _TRADES_VERTICALS or v == "cleaning":
        return "trades"
    return "office"


def _lev_short_strings(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _signature_initial_surname(sig: str) -> tuple[str, str]:
    parts = sig.strip().split()
    if len(parts) >= 2:
        initial = (parts[0].rstrip(".")[:1] or "x").upper()
        return initial, parts[-1].lower()
    return "", sig.strip().lower()


def _adjacent_testimonial_names_too_close(a: str, b: str) -> bool:
    i1, s1 = _signature_initial_surname(a)
    i2, s2 = _signature_initial_surname(b)
    if not s1 or not s2 or i1 != i2:
        return False
    if s1 == s2:
        return True
    if len(s1) >= 4 and len(s2) >= 4 and _lev_short_strings(s1, s2) <= 2:
        return True
    return False


_TESTI_QUOTE_SUFFIX_POOLS: dict[str, tuple[str, ...]] = {
    "legal": (
        " Clear expectations on scope and fees helped.",
        " Written summaries were easy to share with our board.",
        " We would brief them again on a similar matter.",
        " Turnaround on drafts matched what we were told at intake.",
    ),
    "default": (
        " Follow-up was quick and practical.",
        " Communication stayed steady through the job.",
        " Paper trail was easy to forward internally.",
        " Timeline matched what we were told up front.",
        " We would work with them again.",
    ),
}


def _default_testimonials(
    name: str,
    activity: str,
    vertical_id: str,
    brand: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    vid = vertical_id.strip()
    sk = site_key_from_brand(brand or {})
    br = brand or {}
    trng = rng or random.Random(
        int.from_bytes(hashlib.sha256(f"{sk}|testimonial|{vid}".encode()).digest()[:8], "big")
    )
    suffix_pool = _TESTI_QUOTE_SUFFIX_POOLS.get(vid) or _TESTI_QUOTE_SUFFIX_POOLS["default"]
    if vid == "cafe_restaurant":
        quotes = [
            (f"Consistent plates and calm service — {name} is our default for client dinners.", "M. Patel", "Agency director"),
            ("Great food and atmosphere; the wine list actually matches the menu.", "L. Owens", "Regular guest"),
            ("They handled a twenty-person lunch without missing a beat.", "R. Silva", "Office manager"),
            ("Thoughtful vegetarian options, not an afterthought.", "K. Nguyen", "Food writer"),
            ("Reservation team communicated clearly when we shifted the headcount.", "D. Brooks", "Event planner"),
        ]
    elif vid == "cleaning":
        quotes = [
            ("Spot audits match what we see on walkthroughs — rare in this industry.", "T. Malik", "Facility manager"),
            (f"Crews show up in branded kits; tenants stopped complaining about odd smells.", "J. Park", "Property lead"),
            ("They accommodated a floor closure without charging for ghost hours.", "A. Costa", "Ops director"),
            ("SDS binder was organized the way our auditor likes.", "N. Reeves", "EH&S coordinator"),
            ("Night routes actually finish before our open.", "C. Li", "Retail GM"),
        ]
    elif vid == "fitness":
        cy = as_of_year(br)
        fy_i = founded_year_int(br)
        if fy_i is not None:
            msy = max(fy_i, cy - 10)
            if cy > fy_i:
                msy = min(msy, cy - 1)
            member_line = f"Member since {msy}"
        else:
            member_line = f"Member since {max(cy - 5, cy - 8)}"
        quotes = [
            ("Coaches correct form without shaming beginners.", "H. Stone", member_line),
            ("Equipment is maintained; I’ve never waited on a rack for more than a minute.", "B. Irwin", "Powerlifter"),
            ("Trial class felt like a real session, not a sales trap.", "E. Grant", "New member"),
            ("Front desk enforces etiquette — the floor stays workable.", "S. Rao", "Small-group regular"),
        ]
    elif vid == "clothing":
        quotes = [
            ("Measurements on the site matched what arrived — first time in a while.", "G. Holt", "Online shopper"),
            ("Returns were two emails and a label, no arguing.", "P. Dean", "Customer"),
            ("Fabric notes saved me from buying the wrong weight for summer.", "V. Cruz", "Stylist"),
        ]
    elif vid == "news":
        quotes = [
            ("They label opinion clearly and fix mistakes at the top.", "I. Falk", "Reader"),
            ("Briefings save me from doom-scrolling three timelines.", "O. Meyer", "Analyst"),
            ("Tips channel feels supervised by humans.", "Q. Adams", "Researcher"),
        ]
    elif vid == "hvac":
        quotes = [
            (
                f"Emergency call at 11 p.m.; {name} had a tech on-site before morning shift. Rooftop unit stabilized and "
                "they emailed photos for our facilities log.",
                "L. Okonkwo",
                "Property manager",
            ),
            (
                "Mini-split install in a tight laneway house — crew protected floors, explained the thermostat twice, "
                "and the inspection passed first time.",
                "H. Tremblay",
                "Homeowner",
            ),
            (
                f"We compared three quotes; {name} was the only team that walked the mechanical room before pricing. "
                "No surprise change orders.",
                "R. Sandhu",
                "Small-business owner",
            ),
            (
                "Dispatcher kept us in the loop on the two-hour arrival window — rare for trades in our building.",
                "M. Reyes",
                "Office coordinator",
            ),
            (
                "Furnace replacement finished same day; old unit hauled out, paperwork left on the counter for warranty.",
                "G. Foster",
                "Landlord",
            ),
        ]
    elif vid in _TRADES_VERTICALS:
        quotes = [
            (
                f"Same-day callback, clear estimate, and the crew actually showed in the window they promised — "
                f"{name} made {activity} feel managed, not chaotic.",
                "T. Brennan",
                "Homeowner",
            ),
            (
                "We needed documentation for insurance; they sent labeled photos and a short scope letter without chasing.",
                "A. Kowalski",
                "Ops lead",
            ),
            (
                f"Technician explained what failed and what could wait — no pressure to stack extras onto the ticket.",
                "J. Ortiz",
                "Retail manager",
            ),
            (
                "After-hours number reached a human who knew our site; follow-up visit happened next morning.",
                "N. Shah",
                "Facility supervisor",
            ),
        ]
    else:
        quotes = [
            (f"{name} showed up when they said they would and finished without re-quoting mid-job.", "R. Chen", "Property manager"),
            (f"We needed a steady crew for {activity} — estimates matched the final invoice.", "S. Ali", "Small-business owner"),
            ("They explained options in plain language before starting any billable work.", "J. Miller", "Homeowner"),
            ("Scheduling was flexible around our hours; the crew respected the building rules.", "T. Okoro", "Office coordinator"),
            (f"Photos and notes from each visit made it easy to justify renewals on {activity}.", "W. Berg", "Facilities lead"),
        ]
    country = str(br.get("country") or "").strip() or None
    out: list[dict[str, Any]] = []
    for i, (q, _nm, role) in enumerate(quotes):
        qn = q
        if trng.random() < 0.36:
            qn = qn + trng.choice(suffix_pool)
            if trng.random() < 0.18:
                qn = qn + trng.choice(suffix_pool)
        roll = trng.random()
        if roll < 0.11:
            star = "★★★☆☆"
        elif roll < 0.24:
            star = "★★★★☆"
        else:
            star = "★★★★★"
        nm = pick_signature_name(sk, f"testimonial|{vid}|{i}", country=country)
        out.append({"quote": qn, "name": nm, "role": role, "rating": star})
    for j in range(1, len(out)):
        prev_nm = str(out[j - 1].get("name") or "").strip()
        cur_nm = str(out[j].get("name") or "").strip()
        guard = 0
        while (
            prev_nm
            and cur_nm
            and _adjacent_testimonial_names_too_close(prev_nm, cur_nm)
            and guard < 28
        ):
            guard += 1
            cur_nm = pick_signature_name(sk, f"testimonial|{vid}|{j}|d{guard}", country=country)
            out[j]["name"] = cur_nm
    return out


def _default_faq(name: str, city: str, vertical_id: str, rng: random.Random) -> list[dict[str, Any]]:
    vid = vertical_id.strip()
    loc = f" in {city}" if city else ""
    c = city or "our area"
    if vid == "cafe_restaurant":
        items = [
            {"q": "Do you accept reservations?", "a": f"Yes — peak nights fill early; call or use the form and we confirm same day{loc}."},
            {"q": "What are your opening hours?", "a": "Weekday, weekend, and holiday hours are listed on the contact page and updated seasonally."},
            {"q": "Where are you located?", "a": f"We’re in {c} — address, map, and transit notes are on the contact page."},
            {"q": "Do you accommodate allergies?", "a": "Tell your server when you arrive; the kitchen keeps allergen protocols updated."},
            {"q": "Private dining?", "a": "We host small groups with set menus; minimums vary by night."},
            {"q": "Gift cards?", "a": "Available in-house or by email request through the contact form."},
            {"q": "Large parties?", "a": "We set expectations on pacing and deposits before confirming the date."},
            {"q": "Dietary modifications?", "a": "We note modifications on tickets; severe allergies get a kitchen callback before firing."},
        ]
    elif vid == "cleaning":
        items = [
            {"q": "Do you service our building type?", "a": f"We cover offices and retail footprints typical of {c}; walkthroughs are free."},
            {"q": "Are you insured?", "a": "Yes — COI and SDS packets go to your facility contact before day one."},
            {"q": "How do holidays affect routes?", "a": "We shift schedules in advance and confirm with your building manager."},
            {"q": "Can we request photo logs?", "a": "Optional photo checklists are available for high-touch zones."},
            {"q": "Green products?", "a": "We standardize where it meets your spec; substitutions are documented on the work order."},
            {"q": "After-hours access?", "a": "Badging and escort rules are confirmed before the first night shift."},
            {"q": "Quality disputes?", "a": "Supervisors revisit within one business day with photos and a written fix plan."},
            {"q": "Supplies included?", "a": "Standard consumables are included; specialty finishes are quoted separately."},
        ]
    elif vid == "fitness":
        items = [
            {"q": "Do you offer trials?", "a": "Yes — a short tour and one coached session; no pressure to join same day."},
            {"q": "What are opening hours?", "a": "Staffed hours are on the contact page; holiday adjustments post two weeks ahead."},
            {"q": "Where do you park?", "a": f"Street and nearby garages vary by block — we list the best options for {c} on contact."},
            {"q": "Personal training?", "a": "Add-ons available after an on-ramp so programming stays consistent."},
            {"q": "Freeze or hold?", "a": "Medical and travel holds are available with simple written notice."},
            {"q": "Guest policy?", "a": "Guests purchase a day pass; peak classes may require advance booking."},
            {"q": "Youth memberships?", "a": "Age rules vary by program; ask the front desk for the current policy."},
            {"q": "Locker rentals?", "a": "Limited lockers renew monthly; waitlist opens when capacity is full."},
        ]
    elif vid == "clothing":
        items = [
            {"q": "How do returns work?", "a": "Start from the contact form with your order ID; we send a prepaid label where eligible."},
            {"q": "Fit between sizes?", "a": "Use the measurement chart — garment lengths are listed flat and on-body."},
            {"q": "Where do you ship?", "a": "Most regions we serve are listed at checkout; duties notes apply internationally."},
            {"q": "Restock notifications?", "a": "Join the list on the product page; we batch emails to avoid inbox noise."},
            {"q": "Wholesale?", "a": "Select accounts only — use the contact form with your store details."},
        ]
    elif vid == "news":
        items = [
            {"q": "How can I send a tip?", "a": "Use the secure channel linked from the contact page; include how to reach you."},
            {"q": "How do corrections work?", "a": "We place fixes at the top of the story with a timestamp and brief note."},
            {"q": "Republishing policy?", "a": "Credit the byline and link to the canonical piece unless a syndication deal applies."},
            {"q": "Pitch a story?", "a": "Send a tight summary and your deadline; we read everything but cannot reply to all."},
            {"q": "Anonymous sources?", "a": "We document why anonymity is granted and what was verified without naming the source."},
            {"q": "Licensing photos?", "a": "Contact the photo desk with usage, territory, and term — standard fees apply."},
            {"q": "Newsletter?", "a": "Weekly digest links; unsubscribe is one click from every issue."},
            {"q": "API access?", "a": "Enterprise plans include rate limits and attribution requirements."},
        ]
    elif vid == "marketing_agency":
        items = [
            {"q": "What do you need to start an audit?", "a": "Analytics access, Search Console, and stakeholder availability in week one."},
            {"q": "Do you work with in-house teams?", "a": f"Yes — we embed with your marketers and engineers{loc}."},
            {"q": "How do you report progress?", "a": "Shared dashboards plus a written changelog of shipped changes."},
            {"q": "Minimum engagement?", "a": "We quote a discovery block first; retainers follow once scope is stable."},
            {"q": "Tool access?", "a": "We use your stack where possible; sandbox logins beat forwarded screenshots."},
            {"q": "SLAs?", "a": "Response windows are written into the SOW; severity levels define escalation."},
            {"q": "Offboarding?", "a": "You keep repo access, credentials, and documentation in your accounts."},
            {"q": "References?", "a": "We share comparable work under NDA when a serious proposal is in play."},
        ]
    else:
        items = [
            {
                "q": "How do we start a project?",
                "a": rng.choice(
                    [
                        f"Use the contact form — we reply within one business day with next steps{loc}.",
                        f"Contact page first; most threads get a same-day acknowledgment and a clear next step{loc}.",
                    ],
                ),
            },
            {
                "q": "What does a typical engagement include?",
                "a": rng.choice(
                    [
                        "Discovery, a written plan, milestones, and documentation at handoff.",
                        "A short discovery pass, written milestones, and a handoff pack — not a slide deck pretending to be delivery.",
                    ],
                ),
            },
            {
                "q": "Can you sign an NDA?",
                "a": rng.choice(
                    [
                        "Yes — mutual NDA before sharing sensitive details.",
                        "Yes — standard mutual NDA before confidential files or access.",
                    ],
                ),
            },
            {
                "q": "Where are you based?",
                "a": rng.choice(
                    [
                        f"We operate from {c}; full address and hours are on the contact page.",
                        f"{c} is home base; address, map, and hours live on the contact page.",
                    ],
                ),
            },
            {
                "q": "Emergency support?",
                "a": rng.choice(
                    [
                        "After-hours numbers are listed for contracted clients; otherwise email is monitored daily.",
                        "Contracted clients see after-hours lines on their statement of work; everyone else gets next-business-day follow-up.",
                    ],
                ),
            },
            {
                "q": "Payment terms?",
                "a": rng.choice(
                    [
                        "Milestones and net terms are spelled out in the proposal before work starts.",
                        "Net terms and milestone billing are written before signatures — no verbal ‘we’ll figure it out’.",
                    ],
                ),
            },
            {
                "q": "Change requests?",
                "a": rng.choice(
                    [
                        "Scope changes get a short written addendum so dates and budgets stay honest.",
                        "Anything outside scope gets a one-page addendum before more hours hit the invoice.",
                    ],
                ),
            },
            {
                "q": "References?",
                "a": rng.choice(
                    [
                        "We provide relevant references once we’re aligned on scope and timeline.",
                        "Comparable references ship after a serious scope conversation — not as cold-call filler.",
                    ],
                ),
            },
        ]
    rng.shuffle(items)
    take = rng.choice([3, 5, 8])
    return items[: min(take, len(items))]


def _trades_team_roster(brand: dict[str, Any], rng: random.Random, field_role: str) -> list[dict[str, str]]:
    """Site-unique roster; Ireland uses Irish-weighted name pools."""
    country = str(brand.get("country") or "").strip()
    city = str(brand.get("city") or "").strip()
    sk = site_key_from_brand(brand)
    role_sets = [
        ["Owner", field_role, "Scheduling lead", "Service advisor"],
        ["Owner", field_role, "Dispatch", "Service advisor"],
        ["Owner", field_role, "Field coordinator", "Customer lead"],
    ]
    roles = list(rng.choice(role_sets))
    if country == "Ireland" or city == "Dublin":
        roles = ["Owner", field_role, "Operations lead", "Service advisor"]
        return [
            {"name": pick_full_name(sk, f"trades|ie|{i}", variant="irish"), "role": roles[i]}
            for i in range(4)
        ]
    return [
        {
            "name": pick_full_name(sk, f"trades|{country or 'intl'}|{i}", country=country or None),
            "role": roles[i],
        }
        for i in range(4)
    ]


def _ensure_team_items(
    merged: dict[str, Any],
    name: str,
    vertical_id: str,
    brand: dict[str, Any],
    rng: random.Random,
) -> None:
    if merged.get("team_items"):
        return
    merged.setdefault("team_heading", "Meet the team")
    vid = vertical_id.strip()
    sk = site_key_from_brand(brand)
    team_ctry = str(brand.get("country") or "").strip() or None

    def _person(slot: str, role: str, bio: str = "") -> dict[str, Any]:
        row: dict[str, Any] = {"name": pick_full_name(sk, f"{vid}|{slot}", country=team_ctry), "role": role}
        if bio:
            row["bio"] = bio
        return row

    if vid == "cafe_restaurant":
        merged["team_items"] = [
            _person("chef", "Executive chef"),
            _person("gm", "General manager"),
            _person("pastry", "Pastry lead"),
            _person("somm", "Sommelier"),
        ]
    elif vid == "cleaning":
        merged["team_items"] = [
            _person("ops", "Operations manager"),
            _person("field", "Field supervisor"),
            _person("qc", "Quality lead"),
            _person("support", "Client support"),
        ]
    elif vid == "fitness":
        merged["team_items"] = [
            _person("coach", "Head coach"),
            _person("programs", "Program director"),
            _person("membership", "Membership manager"),
        ]
    elif vid == "clothing":
        merged["team_items"] = [
            _person("creative", "Creative director"),
            _person("production", "Production lead"),
            _person("fit", "Fit & quality"),
            _person("cx", "Customer support"),
        ]
    elif vid == "marketing_agency":
        merged["team_items"] = [
            _person("strategy", "Strategy lead"),
            _person("seo", "Technical SEO"),
            _person("content", "Content director"),
        ]
    elif vid == "accounting":
        merged["team_items"] = [
            _person(
                "cpa",
                "Senior Accountant, CPA",
                "Corporate and trust filings, year-end close, and CRA correspondence — clients get plain-language answers.",
            ),
            _person(
                "tax",
                "Tax Associate",
                "GST/HST reviews, T2 packages, and instalment calendars so owners are not surprised in April or June.",
            ),
            _person(
                "book",
                "Bookkeeping Lead",
                "Day-to-day AP/AR, reconciliations, and month-end packages your lender or auditor can follow.",
            ),
            _person(
                "cx",
                "Client Manager",
                "Single point of contact for deadlines, document requests, and scope — no mystery inbox.",
            ),
        ]
    elif vid == "legal":
        merged["team_items"] = [
            _person(
                "assoc",
                "Associate",
                "Drafting, diligence, and transaction timelines — keeps deals moving without burying clients in jargon.",
            ),
            _person(
                "partner",
                "Partner",
                "Risk calls in writing, escalation when facts shift, and files organized for successor counsel if needed.",
            ),
            _person(
                "clerk",
                "Law Clerk",
                "Research memos, filing checklists, and court deadlines tracked so nothing depends on one calendar.",
            ),
        ]
    elif vid == "hvac":
        merged["team_items"] = [
            _person("owner", "Owner"),
            _person("lead-tech", "Lead service technician"),
            _person("dispatch", "Dispatcher"),
            _person("install", "Install lead"),
            _person("advisor", "Service advisor"),
        ]
    elif vid in _TRADES_VERTICALS:
        field_role = "Lead technician"
        if vid in ("landscaping", "moving"):
            field_role = "Crew lead"
        elif vid == "auto_repair":
            field_role = "Master technician"
        merged["team_items"] = _trades_team_roster(brand, rng, field_role)
    elif vid == "news":
        # Keep About/Team consistent with the generated newsroom authors list.
        auth = merged.get("news_authors")
        if isinstance(auth, list) and auth:
            merged["team_items"] = [
                {"name": str(a.get("name") or "").strip(), "role": str(a.get("title") or "").strip()}
                for a in auth[:3]
                if isinstance(a, dict) and str(a.get("name") or "").strip()
            ]
        if not merged.get("team_items"):
            merged["team_items"] = [
                _person("news-eic", "Editor-in-chief"),
                _person("news-me", "Managing editor"),
            ]
    else:
        merged["team_items"] = [
            _person("delivery", "Delivery lead"),
            _person("success", "Client success"),
            _person("ops", "Operations"),
        ]
    # Make this section feel real: either omit team, or show more than two people.
    items = list(merged.get("team_items") or [])
    if vid == "accounting":
        merged["team_items"] = items[:4]
    elif vid == "legal":
        merged["team_items"] = items[:3]
    elif vid == "news":
        merged["team_items"] = items[:3]
    elif vid == "clothing":
        merged["team_items"] = items[: rng.choice([4, 5])]
    elif vid == "hvac":
        merged["team_items"] = items[: rng.choice([4, 5])]
    elif vid in _TRADES_VERTICALS:
        merged["team_items"] = items[: rng.choice([3, 4])]
    else:
        merged["team_items"] = items[:3]


def _ensure_component_defaults(
    base: dict[str, Any],
    name: str,
    activity: str,
    vertical_id: str,
    brand: dict[str, Any],
    rng: random.Random,
) -> None:
    """Guarantee data for testimonials / faq / gallery when theme pack has no overlay (e.g. generic vertical)."""
    city = str(brand.get("city") or "").strip()
    if not base.get("testimonial_items"):
        base.setdefault("testimonials_heading", "What clients say")
        base["testimonial_items"] = _default_testimonials(name, activity, vertical_id, brand=brand, rng=rng)
    if not base.get("faq_items"):
        base.setdefault("faq_heading", "Frequently asked questions")
        base["faq_items"] = _default_faq(name, city, vertical_id, rng)
    if not base.get("gallery_items"):
        _prof_v = frozenset({"legal", "consulting", "medical", "dental", "accounting"})
        if vertical_id.strip() in _prof_v:
            base["gallery_heading"] = ""
            base["gallery_items"] = []
        else:
            base.setdefault("gallery_heading", "Gallery")
            base["gallery_items"] = [
                {"caption": "Program kickoff"},
                {"caption": "Work session"},
                {"caption": "Launch milestone"},
            ]
    if not (base.get("services_seo_description") or "").strip():
        intro = (base.get("services_intro") or "").strip()
        base["services_seo_description"] = (
            (intro[:220] + "…") if len(intro) > 220 else intro or f"{name} — focused work in {activity}."
        )


def _fake_client_company(rng: random.Random) -> str:
    a = [
        "Northwind",
        "BlueHarbor",
        "RiverStone",
        "CedarLine",
        "MetroLink",
        "SummitRail",
        "BayPoint",
        "OakField",
        "KiteRock",
        "SilverMaple",
        "IronGate",
        "RedBrick",
        "ClearFork",
        "GraniteRow",
        "HarborLine",
        "Pinewood",
        "CopperField",
        "LakePoint",
        "BridgeWell",
    ]
    b = [
        "Holdings",
        "Group",
        "Partners",
        "Works",
        "Supply",
        "Studios",
        "Clinic",
        "Properties",
        "Logistics",
        "Retail",
        "Foods",
        "Communities",
    ]
    return f"{rng.choice(a)} {rng.choice(b)}"


def _enrich_testimonial_items(merged: dict[str, Any], brand: dict[str, Any], rng: random.Random) -> None:
    items = merged.get("testimonial_items")
    if not isinstance(items, list):
        return
    name_fb = str(brand.get("brand_name") or merged.get("brand_name") or "Brand")
    activity_fb = str(merged.get("activity_summary") or "services")
    vid_fb = str(merged.get("vertical_id") or "").strip()
    quote_defaults = _default_testimonials(name_fb, activity_fb, vid_fb, brand, rng=rng)
    zones = brand.get("service_area_zones")
    zone_list = [str(z) for z in zones] if isinstance(zones, list) else [str(brand.get("city") or "Local area")]
    styles = ["long", "short", "detail", "micro"]
    seen_quotes: set[str] = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        q0 = str(it.get("quote") or "").strip()
        if not q0:
            if quote_defaults:
                it["quote"] = str(quote_defaults[min(i, len(quote_defaults) - 1)].get("quote") or "").strip()
            if not str(it.get("quote") or "").strip():
                it["quote"] = (
                    f"{name_fb} kept communication clear and delivered solid results on {activity_fb} — we would work with them again."
                )
        q_norm = " ".join(str(it.get("quote") or "").split()).strip().lower()[:240]
        if q_norm and q_norm in seen_quotes and quote_defaults:
            alt = str(quote_defaults[min(i + 1, len(quote_defaults) - 1)].get("quote") or "").strip()
            if alt and alt.lower()[:240] != q_norm:
                it["quote"] = alt
                q_norm = " ".join(str(it.get("quote") or "").split()).strip().lower()[:240]
        q_cur = " ".join(str(it.get("quote") or "").split()).strip()
        pool = _TESTI_QUOTE_SUFFIX_POOLS.get(vid_fb) or _TESTI_QUOTE_SUFFIX_POOLS["default"]
        if q_cur and len(q_cur) < 400 and rng.random() < 0.44:
            suf = rng.choice(pool)
            tail = q_cur[-100:].lower()
            if suf.strip()[:14].lower() not in tail:
                q_cur = q_cur + suf
            if len(q_cur) < 520 and rng.random() < 0.2:
                suf2 = rng.choice(pool)
                if suf2 != suf and suf2.strip()[:14].lower() not in q_cur[-120:].lower():
                    q_cur = q_cur + suf2
            it["quote"] = q_cur
            q_norm = " ".join(q_cur.split()).strip().lower()[:240]
        if q_norm:
            seen_quotes.add(q_norm)
        if not (it.get("city") or "").strip():
            it["city"] = rng.choice(zone_list)
        try:
            avg_target = float(str(brand.get("review_avg") or "4.5"))
        except ValueError:
            avg_target = 4.5
        roll_st = rng.random()
        if roll_st < 0.12:
            stars_n = 3
        elif roll_st < 0.26:
            stars_n = 4
        else:
            jittered = avg_target + rng.uniform(-0.75, 0.75)
            stars_n = min(5, max(3, int(round(jittered))))
        it["rating_score"] = stars_n
        it["rating"] = "★" * stars_n + "☆" * (5 - stars_n)
        it["style"] = rng.choice(styles)
        it["has_photo"] = rng.random() < 0.42
        it.setdefault("photo_src", "")
        if vid_fb == "pest_control":
            plat = [
                "Google review",
                "Google Maps",
                "Facebook",
                "Nextdoor",
                "Homeowner referral",
                "Property manager referral",
                "",
            ]
        elif vid_fb == "cleaning":
            plat = [
                "Google review",
                "Google Maps",
                "Facebook",
                "Yelp",
                "Trusted cleaner referral",
                "",
            ]
        else:
            plat = ["Google review", "Google Maps", "Facebook", "Yelp", "Neighbor referral", ""]
        it["source_label"] = rng.choice(plat) if rng.random() < 0.78 else ""

    sk_tm = site_key_from_brand(brand)
    country_tm = str(brand.get("country") or "").strip() or None
    for j in range(1, len(items)):
        prev = items[j - 1]
        cur = items[j]
        if not isinstance(prev, dict) or not isinstance(cur, dict):
            continue
        n0 = str(prev.get("name") or "").strip()
        n1 = str(cur.get("name") or "").strip()
        guard = 0
        while n0 and n1 and _adjacent_testimonial_names_too_close(n0, n1) and guard < 28:
            guard += 1
            n1 = pick_signature_name(sk_tm, f"tstm-adj|{vid_fb}|{j}|{guard}", country=country_tm)
            cur["name"] = n1


def _enrich_hero_footer_trust(merged: dict[str, Any], brand: dict[str, Any], rng: random.Random) -> None:
    """Random trust/rating lines for hero and footer variants that opt into them."""
    ra = brand.get("review_avg")
    rc = brand.get("review_count")
    pub = brand.get("schema_publish_aggregate_rating", True)
    show_rating = (
        pub
        and ra is not None
        and rc is not None
        and rng.random() < 0.62
    )
    merged["hero_show_rating"] = show_rating
    merged["hero_rating_summary"] = (
        f"{ra}/5 average from {rc}+ local reviews" if show_rating else ""
    )
    bullets: list[str] = []
    vid_ht = str(merged.get("vertical_id") or "").strip()
    trade_hero = vid_ht in _TRADES_VERTICALS or vid_ht in ("dental", "medical", "cleaning", "pest_control")
    lic = brand.get("licenses")
    if isinstance(lic, list) and lic and rng.random() < 0.48:
        bullets.append(f"Licensed: {rng.choice(lic)}")
    cert = brand.get("certifications")
    if isinstance(cert, list) and cert and rng.random() < 0.42:
        bullets.append(str(rng.choice(cert)))
    ins = str(brand.get("insurance") or "").strip()
    if ins and rng.random() < 0.38:
        bullets.append(ins)
    if vid_ht == "cafe_restaurant":
        hw = str(brand.get("hours_weekday") or "").strip()
        we = str(brand.get("hours_weekend") or "").strip()
        if hw and rng.random() < 0.55:
            bullets.append(hw.split("·")[0].strip() if "·" in hw else hw)
        if we and rng.random() < 0.5:
            bullets.append(we)
        if rng.random() < 0.45:
            bullets.append(rng.choice(["Reservations recommended Fri–Sat", "Walk-ins when tables allow"]))
        if rng.random() < 0.4:
            bullets.append(rng.choice(["Seasonal menu updates weekly", "Wine list rotates with the kitchen"]))
    else:
        if trade_hero and rng.random() < 0.35:
            bullets.append("Same-day dispatch when slots allow")
        if trade_hero and rng.random() < 0.28:
            bullets.append("Written estimates before work begins")
    rng.shuffle(bullets)
    merged["hero_trust_bullets"] = bullets[:4]

    trust_bits: list[str] = []
    if isinstance(lic, list) and lic:
        trust_bits.append(str(rng.choice(lic)))
    if isinstance(cert, list) and cert:
        trust_bits.append(str(rng.choice(cert)))
    if ins:
        trust_bits.append(ins)
    rng.shuffle(trust_bits)
    merged["footer_trust_strip"] = " · ".join(trust_bits[:3]) if trust_bits and rng.random() < 0.55 else ""

    tips = merged.get("testimonial_items")
    bn = str(brand.get("brand_name") or "Site")
    if isinstance(tips, list) and tips and rng.random() < 0.36:
        pick: Any = tips[0]
        if len(tips) > 1:
            ident_fb = str(brand.get("generation_identity") or merged.get("generation_identity") or bn)
            foot_h = int(hashlib.sha256(f"footer_rev|{ident_fb}".encode("utf-8")).hexdigest(), 16)
            idx = 1 + (foot_h % (len(tips) - 1))
            alt = tips[idx]
            if isinstance(alt, dict) and isinstance(pick, dict):
                q0 = str(pick.get("quote") or "").strip()
                if str(alt.get("quote") or "").strip() != q0:
                    pick = alt
                else:
                    for cand in tips[1:]:
                        if isinstance(cand, dict) and str(cand.get("quote") or "").strip() != q0:
                            pick = cand
                            break
        first = pick
        if isinstance(first, dict):
            q = str(first.get("quote") or "").strip()
            if len(q) > 150:
                q = q[:147] + "…"
            nm = str(first.get("name") or "Customer").strip()
            merged["footer_review_snippet"] = f"“{q}” — {nm}" if q else ""
        else:
            merged["footer_review_snippet"] = ""
    else:
        merged["footer_review_snippet"] = ""

    city = str(brand.get("city") or "").strip()
    act = str(merged.get("activity_summary") or "services")
    hero_alt_pool = [
        f"{bn} — {city}" if city else bn,
        f"{bn} in {city}" if city else f"Photo — {bn}",
        f"{bn}: {act} project context",
        f"Visual for {bn}",
        f"{bn} team and workspace" if not city else f"{bn} local work in {city}",
    ]
    merged["hero_image_alt"] = rng.choice(hero_alt_pool)


def _service_process_steps_for_item(
    item: dict[str, Any],
    activity: str,
    city: str,
    svc_index: int,
) -> list[dict[str, str]]:
    """Distinct 3-step flows per service card (avoids identical Scope/Prep/Deliver on every column)."""
    title = str(item.get("title") or "Service").strip()
    t = title.lower()
    act = (activity or "work").strip().lower()
    cbit = f" around {city}" if (city or "").strip() else ""
    h = int(hashlib.sha256(f"svcsteps|{title}|{svc_index}".encode("utf-8")).hexdigest(), 16)
    pools: list[list[dict[str, str]]] = [
        [
            {"label": "Intake", "text": f"We confirm scope for {t}{cbit}, access, and who approves changes."},
            {"label": "Mobilize", "text": "Crews, materials, and comms paths are lined up before the first on-site hour."},
            {"label": "Verify", "text": "Work follows the agreed checklist; we capture sign-off and any punch items."},
        ],
        [
            {"label": "Discovery", "text": f"A short walkthrough to map constraints for {t} before we quote."},
            {"label": "Schedule", "text": "We lock dates with your building or tenant contacts and safety notes."},
            {"label": "Handoff", "text": "You get a concise wrap summary with photos or readings where useful."},
        ],
        [
            {"label": "Align", "text": f"We match {act} expectations to site realities — no mystery scope."},
            {"label": "Execute", "text": "Technicians work to a written sequence with pause points for approvals."},
            {"label": "Document", "text": "Notes, warranties, and next-service suggestions land in one place."},
        ],
        [
            {"label": "Quote", "text": "Written estimate with assumptions, exclusions, and a realistic window."},
            {"label": "Prep", "text": "Permits, parts, and site protection sorted before tools hit the floor."},
            {"label": "Close", "text": "Final test, cleanup, and a walkthrough with your on-site contact."},
        ],
        [
            {"label": "Book", "text": "We confirm arrival windows and parking or dock access ahead of time."},
            {"label": "Work", "text": f"{title} is delivered in staged steps so you can keep operating."},
            {"label": "Review", "text": "We recap what changed and what to watch over the next few weeks."},
        ],
        [
            {"label": "Scope", "text": f"Define success for {t}: measurements, materials, and stop conditions."},
            {"label": "Stage", "text": "Tools, PPE, and site contacts are confirmed the day before arrival."},
            {"label": "Deliver", "text": "Execution against the checklist with verification you can audit."},
        ],
        [
            {"label": "Listen", "text": "We capture priorities, no-go areas, and escalation contacts up front."},
            {"label": "Plan", "text": "A one-page plan with milestones — edits stay visible, not verbal-only."},
            {"label": "Finish", "text": "Quality check, debris handling, and a clear “done” definition."},
        ],
        [
            {"label": "Assess", "text": f"Quick site read for {t} so estimates reflect real access and risk."},
            {"label": "Coordinate", "text": "We sync with your ops calendar and any third-party vendors."},
            {"label": "Wrap", "text": "Sign-off package with maintenance tips and warranty pointers."},
        ],
        [
            {"label": "Kickoff", "text": f"Confirm utilities, lockout/tagout needs, and working hours for {act}."},
            {"label": "Build", "text": "Progress checkpoints match the agreed sequence — surprises get logged early."},
            {"label": "Train", "text": "If needed, a 10-minute operator briefing on what we changed and why."},
        ],
    ]
    return pools[h % len(pools)]


def _build_about_timeline_rows(
    name: str, fy: int, cy: int, rng: random.Random, vertical_id: str = ""
) -> list[dict[str, str]]:
    y0 = max(1970, min(int(fy), int(cy)))
    vid = (vertical_id or "").strip()
    if vid == "accounting":
        labels = [
            "First busy personal tax season with a documented intake-to-filing checklist.",
            "Moved bookkeeping and payroll clients to a shared month-end close rhythm.",
            "Expanded corporate T2 and GST review capacity with CPA-reviewed workpaper standards.",
        ]
        open_lab = f"{name} opens — focused on bookkeeping, year-end, and personal tax for local operators."
    elif vid == "legal":
        labels = [
            "First retained corporate client with a written conflicts and intake protocol.",
            "Formalized litigation and transactions playbooks with junior staffing ratios.",
            "Added specialty counsel panels for employment and regulatory-heavy files.",
        ]
        open_lab = f"{name} opens — corporate and litigation support with clear retainer and disclosure habits."
    elif vid in ("hvac", "plumbing", "electrical", "roofing"):
        labels = [
            "First seasonal tune-up program with documented filter and safety checks.",
            "Expanded licensed crew coverage and after-hours dispatch for urgent calls.",
            "Standardized load documentation and warranty handoffs on installs.",
        ]
        open_lab = f"{name} opens — licensed field service with clear scopes and written estimates."
    elif vid == "pest_control":
        labels = [
            "First integrated pest management plan with exterior barrier and interior monitoring.",
            "Added licensed applicators for multi-unit and food-service routes.",
            "Documented re-treatment windows and customer prep so callbacks stay predictable.",
        ]
        open_lab = f"{name} opens — inspection-first pest control with labeled treatment plans."
    elif vid in ("consulting", "marketing_agency", "real_estate"):
        labels = [
            "First long-term anchor client on retainer.",
            "Expanded delivery bench and standardized onboarding for new accounts.",
            "Reworked proposals and reporting so expectations stay explicit quarter to quarter.",
        ]
        open_lab = f"{name} opens for business locally."
    else:
        labels = [
            "First repeat commercial account with a written scope and renewal rhythm.",
            "Expanded crew and standardized safety and tool checks.",
            "Reworked routes and job documentation so handoffs stay consistent.",
        ]
        open_lab = f"{name} opens for business locally."
    rows: list[dict[str, str]] = [
        {"year": str(y0), "label": open_lab},
    ]
    if cy <= y0:
        return rows
    span = cy - y0
    n_mid = min(2, max(0, span - 2))
    prev = y0
    for j in range(n_mid):
        frac = (j + 1) / (n_mid + 1)
        tgt = y0 + max(1, int(round(span * frac)) + rng.randint(-1, 1))
        tgt = max(prev + 1, min(cy - 1, tgt))
        prev = tgt
        rows.append({"year": str(tgt), "label": labels[j]})
    if cy > prev:
        last_lab = labels[n_mid] if n_mid < len(labels) else labels[-1]
        rows.append({"year": str(cy), "label": last_lab})
    else:
        rows[-1] = {"year": str(cy), "label": rows[-1]["label"]}
    return rows


def _careers_opening_blurb(
    title: str,
    *,
    name: str,
    activity: str,
    city: str,
    rng: random.Random,
    vertical_id: str = "",
) -> str:
    """Role- and vertical-specific copy (trades vs office vs clinical, etc.)."""
    loc = city or "the local area"
    t = (title or "").lower()
    family = _careers_copy_family(vertical_id)

    if family == "office":
        if any(k in t for k in ("intern", "trainee", "student", "articling")) or "graduate hire" in t:
            return rng.choice(
                [
                    f"Rotational exposure to {activity} work at {name} — close supervision, structured feedback, and clear competency milestones.",
                    "Entry track with documented training, ethics and confidentiality expectations, and increasing responsibility as you prove judgment.",
                    f"Learn how {name} runs matters end to end: research hygiene, client communication, and quality bars before you own client-facing work.",
                ],
            )
        if "lawyer" in t or "counsel" in t:
            return rng.choice(
                [
                    f"Own a portfolio of {activity} matters with partner oversight — research, drafting, and client contact that meet professional standards.",
                    f"Deliver work product {name} can file or send with confidence: clear analysis, tight citations, and calm communication under deadlines.",
                    "Mid-level practice role — supervise juniors on discrete tasks, manage timelines, and keep files organized for review.",
                ],
            )
        if any(
            k in t
            for k in (
                "paralegal",
                "bookkeeper",
                "reception",
                "legal assistant",
                "administrative assistant",
                "office assistant",
            )
        ):
            return rng.choice(
                [
                    f"Keep files, calendars, and client touchpoints organized so {name}'s professionals can focus on {activity} delivery.",
                    "Support role with high standards for accuracy, discretion, and follow-through — you’ll own repeatable workflows others rely on.",
                    f"Front line for intake and documentation: triage requests, prep materials, and make sure nothing slips between meetings and deadlines.",
                ],
            )
        if "assistant" in t and "lawyer" not in t:
            return rng.choice(
                [
                    f"Keep files, calendars, and client touchpoints organized so {name}'s professionals can focus on {activity} delivery.",
                    "Support role with high standards for accuracy, discretion, and follow-through — you’ll own repeatable workflows others rely on.",
                    f"Front line for intake and documentation: triage requests, prep materials, and make sure nothing slips between meetings and deadlines.",
                ],
            )
        return rng.choice(
            [
                f"Own a slice of client work in {activity} — clear ownership, partner-level review, and deliverables you’re proud to put the firm name on.",
                f"Deliver analysis and recommendations for {name}'s clients with disciplined process, sensible deadlines, and direct leadership access.",
                f"Guide quality on {activity} engagements; you’ll mentor juniors when relevant and keep outputs audit-ready.",
            ],
        )

    if family == "creative":
        if "junior" in t or "intern" in t or "coordinator" in t:
            return rng.choice(
                [
                    f"Support campaigns and reporting for {name} — learn our stack, ship small wins weekly, and grow toward owning a channel.",
                    "Hands-on coordinator track: briefs, QA checks, and client-ready updates with a coach who still does the craft.",
                    f"Entry role focused on execution discipline across {activity} — templates, checklists, and feedback loops that build good habits fast.",
                ],
            )
        if "account" in t:
            return rng.choice(
                [
                    f"Be the day-to-day contact for key accounts — scope control, timelines, and calm updates when {activity} work gets busy.",
                    "Translate client goals into actionable tasks for the team; you own the rhythm between stakeholders and delivery.",
                    f"Grow relationships while protecting margin: clear change orders, honest status, and proactive risk flags for {name}.",
                ],
            )
        return rng.choice(
            [
                f"Shape strategy and shipped work for {activity} — strong opinions, weakly held, with data and tests to settle debates.",
                f"Own narrative and structure for {name}'s deliverables; editors and engineers should both recognize the standard you set.",
                "Senior craft role: mentor juniors, protect brand voice, and keep output defensible when clients ask hard questions.",
            ],
        )

    if family == "editorial":
        if "intern" in t or "assistant" in t:
            return rng.choice(
                [
                    "Support the newsroom with research, fact checks, and production tasks — accuracy and speed both matter.",
                    f"Learn {name}'s standards for sourcing and corrections while contributing to daily publishing rhythms.",
                    "Desk work that touches real stories: logging tips, verifying details, and keeping editors unblocked.",
                ],
            )
        if "reporter" in t or "correspondent" in t:
            return rng.choice(
                [
                    f"Report and write for {name} with named sourcing, proportionate skepticism, and clean explainers readers can reuse.",
                    "Field and desk reporting — verify before you amplify, document what you know vs. infer, and update when facts move.",
                    f"Own a beat tied to {activity}: pitch, report, and publish with an editor who pushes clarity over heat.",
                ],
            )
        return rng.choice(
            [
                f"Edit or produce for {name} — protect readers’ time, enforce corrections policy, and keep publishing calm under deadline.",
                "Shape coverage and packaging; you’ll balance speed with verification and make hard cuts when the story is overcrowded.",
                f"Run production threads so {activity} output ships clean: headlines, decks, and last-mile checks before publish.",
            ],
        )

    if family == "hospitality":
        if "prep" in t or "junior" in t:
            return rng.choice(
                [
                    f"Kitchen foundation role at {name} — mise, timing, and station discipline during real service pressure.",
                    "Learn the line from the prep table up: recipes, safety, and how we protect consistency on busy nights.",
                    "Entry kitchen track with a clear path toward line responsibility once speed and standards hold.",
                ],
            )
        if "front" in t or "supervisor" in t:
            return rng.choice(
                [
                    f"Lead the dining room for {name} — reservations, pacing, and guest recovery when the room gets loud.",
                    "FOH ownership: train hosts and servers, protect the guest experience, and keep communication tight with the kitchen.",
                    f"Service supervisor who can read the room, coach under stress, and keep {activity} hospitality consistent.",
                ],
            )
        return rng.choice(
            [
                f"Sous-level execution for {name} — standards on the pass, costing awareness, and calm leadership when tickets stack.",
                "Run a station with authority: plating, timing, and coaching juniors without losing the thread during peak.",
                f"Senior kitchen role tied to {activity} — menu discipline, vendor coordination, and quality that holds on the busiest shifts.",
            ],
        )

    if family == "fitness":
        if "floor" in t or "junior" in t:
            return rng.choice(
                [
                    f"Member-facing floor role at {name} — equipment etiquette, safety watch, and helpful coaching within your scope.",
                    "Learn the gym’s culture and protocols; you’ll support classes, rack weights, and keep the space professional.",
                    "Junior track with a path toward coaching credentials once movement standards and member care are second nature.",
                ],
            )
        if "membership" in t or "advisor" in t:
            return rng.choice(
                [
                    f"Help people choose the right membership and onboarding path for {name} — honest fit over quick sales.",
                    "Front-desk leadership: trials, renewals, and clear answers about schedules, coaches, and policies.",
                    f"Advisory role for {activity} programs — listen first, recommend second, and document follow-ups the team can execute.",
                ],
            )
        if "instructor" in t:
            return rng.choice(
                [
                    f"Coach capped classes for {name} — form-first teaching, music and pacing that match the room, and safety non-negotiables.",
                    "Plan and deliver group sessions with progressions beginners can follow and veterans still respect.",
                    f"Group programming tied to {activity}: warm-ups, scaling options, and end-to-end accountability for the hour.",
                ],
            )
        return rng.choice(
            [
                f"Head coach standards at {name} — mentor staff, protect programming quality, and keep the floor culture disciplined.",
                "Senior coaching role: staff development, conflict handling, and member experience when the gym is at capacity.",
                f"Lead the training philosophy for {activity} — progression rules, equipment care, and how we talk about risk.",
            ],
        )

    if family == "retail":
        if "support" in t:
            return rng.choice(
                [
                    f"Resolve customer issues for {name} with clear policies, fast follow-up, and tone that protects the brand.",
                    "Inbox and chat ownership — sizing, shipping, and returns with answers that reduce back-and-forth.",
                    f"Support {activity} shoppers with accurate product guidance and calm handling when expectations miss.",
                ],
            )
        if "fulfillment" in t or "operations" in t:
            return rng.choice(
                [
                    f"Own pick/pack accuracy and carrier cutoffs for {name} — inventory hygiene and zero-drama handoffs to carriers.",
                    "Back-of-house operations: stock moves, QC spot checks, and metrics when volumes spike.",
                    f"Keep {activity} orders flowing — barcodes, exceptions, and communication when an item can’t ship as promised.",
                ],
            )
        return rng.choice(
            [
                f"Coordinate digital merchandising and launches for {name} — assets, copy handoffs, and launch checklists that hold under traffic.",
                f"Cross-functional role between site, studio, and ops so {activity} drops stay coherent end to end.",
                "E-com ops with an eye for detail: collections updates, broken links, and the boring fixes customers actually notice.",
            ],
        )

    if family == "healthcare":
        if "reception" in t or ("administrative" in t and "assistant" in t):
            return rng.choice(
                [
                    f"First touch for patients at {name} — scheduling, forms, and calm coordination when the clinic runs behind.",
                    "Front desk with privacy discipline: triage calls, verify insurance basics, and keep providers on schedule.",
                    f"Patient-facing admin for {activity} — clear instructions, compassionate tone, and accurate records.",
                ],
            )
        if "coordinator" in t:
            return rng.choice(
                [
                    f"Coordinate treatment plans and follow-ups for {name} — documentation, reminders, and handoffs clinicians trust.",
                    "Own the thread between clinical staff and patients: prep instructions, timing, and post-visit checklists.",
                    f"Ops-aware coordinator for {activity} — supplies, room turnover, and the small details that prevent bottlenecks.",
                ],
            )
        if "nurse" in t or "hygienist" in t:
            return rng.choice(
                [
                    f"Licensed clinical support for {name} — protocol-driven care, impeccable charting, and teamwork under time pressure.",
                    "Deliver hands-on care with consent, clarity, and standards your peers can audit without drama.",
                    f"Patient-centered clinical work in {activity} — safety, empathy, and consistency visit to visit.",
                ],
            )
        return rng.choice(
            [
                f"Chairside and clinic support for {name} — instrument prep, infection control, and assistants who anticipate the next step.",
                "Clinical support role with strict hygiene and documentation habits; you make providers faster without cutting corners.",
                f"Support {activity} delivery with steady hands, calm patients, and supplies that are always where they should be.",
            ],
        )

    if family == "real_estate":
        if "junior" in t or "trainee" in t:
            return rng.choice(
                [
                    f"Learn the business at {name} — showings prep, CRM hygiene, and deal paperwork with senior oversight.",
                    "Trainee track: compliance basics, client communication templates, and how we protect time on busy weekends.",
                    f"Entry path in {activity} — research, listing support, and increasing ownership as licenses and skills line up.",
                ],
            )
        if "showing" in t or "transaction" in t:
            return rng.choice(
                [
                    f"Coordinate showings and calendars for {name} — lockboxes, confirmations, and last-minute changes without chaos.",
                    "Transaction desk discipline: deadlines, disclosures, and files an auditor could open without wincing.",
                    f"Keep {activity} deals moving — vendors, clients, and agents all hear the same facts at the same time.",
                ],
            )
        return rng.choice(
            [
                f"Represent buyers and sellers with {name} — market truth, negotiation discipline, and paperwork you can defend.",
                f"Sales associate focused on {loc}: listings, tours, and follow-up that respects clients’ timelines, not just ours.",
                f"Grow a book of business inside {name}'s standards for {activity} — referrals should feel inevitable, not accidental.",
            ],
        )

    # --- trades & cleaning (field crews, tools, PPE) ---
    if "apprentice" in t or "trainee" in t:
        return rng.choice(
            [
                f"Structured entry into {activity}: mentorship, safety and tool fundamentals, then progressively owning "
                "small scopes with senior sign-off.",
                f"Learn {activity} on real jobs with a written training plan, PPE provided, and clear checkpoints before you work unsupervised.",
                "Paid development track — classroom and field time, documented competencies, and a path toward full technician responsibilities.",
            ],
        )
    if "coordinator" in t or ("client" in t and "field" not in t):
        return rng.choice(
            [
                f"Own intake, scheduling, and follow-up so {name}'s crews arrive with context and clients stay informed end to end.",
                f"Bridge customers and operations — scopes, change notes, and paperwork that keep {activity} work unblocked.",
                f"Front-door discipline: triage requests, align calendars, and make sure nothing falls between email threads and the job site.",
            ],
        )
    if "operations" in t:
        return rng.choice(
            [
                f"Keep routes, vendors, and checklists aligned so {activity} delivery stays predictable week to week.",
                "Back-office spine for the team — dispatch support, QA spot checks, and metrics that surface issues early.",
                f"Tune the machine behind {activity}: inventory, subcontractor touchpoints, and handoffs crews can rely on.",
            ],
        )
    if "field" in t or (t.startswith("lead") or " lead" in t):
        return rng.choice(
            [
                f"Lead on-site work for {activity} across {loc}: safety briefs, quality gates, and clear escalation when conditions shift.",
                f"Hands-on lead — set the standard on the truck, coach newer techs, and own accountable handoffs after each visit.",
                f"Run crews through busy days in {loc}: job sequencing, customer touchpoints, and closing punch lists without rework.",
            ],
        )
    return rng.choice(
        [
            f"Work alongside a focused team on {activity} in {loc}. Training provided; safety and documentation are non-negotiable.",
            f"Contribute to {activity} delivery with clear ownership, written procedures, and room to grow as the roster expands.",
        ],
    )


# Process page: fixed order (never shuffle). Copy matches vertical — no "crews" on accounting sites.
_PROCESS_STEPS_TRADES: tuple[dict[str, str], ...] = (
    {"title": "Intake", "text": "We confirm access, timing, compliance needs, and who signs off."},
    {"title": "Mobilize", "text": "Crews and materials are staged so the first day is productive."},
    {"title": "Execute", "text": "Work proceeds against an agreed checklist with verification."},
    {"title": "Walkthrough", "text": "We review outcomes with your contact and capture punch-list items."},
    {"title": "Close-out", "text": "Paperwork, warranties, and next steps are bundled in one package."},
)
_PROCESS_STEPS_ACCOUNTING: tuple[dict[str, str], ...] = (
    {
        "title": "Intake & scoping",
        "text": "We align on entity structure, fiscal year-end, bookkeeping tools, and which filings apply (GST, payroll, T2).",
    },
    {
        "title": "Books & documentation",
        "text": "Chart of accounts, bank and card reconciliations, and a clean trail for receipts, invoices, and T-slips.",
    },
    {
        "title": "Monthly or periodic close",
        "text": "Adjusting entries, management reports, and review notes before anything goes to CRA or lenders.",
    },
    {
        "title": "Tax & compliance prep",
        "text": "Corporate and owner filings scoped with clear assumptions — no last-minute surprises on T4/T5 or GST lines.",
    },
    {
        "title": "Close-out & handoff",
        "text": "Filed returns, payment vouchers summarized, and next-year calendar with CRA deadlines blocked in advance.",
    },
)
_PROCESS_STEPS_LEGAL: tuple[dict[str, str], ...] = (
    {
        "title": "Intake & conflicts",
        "text": "We confirm the matter, timeline, budget band, run conflicts, and name who can instruct us day to day.",
    },
    {
        "title": "Strategy & research",
        "text": "Issue spotting, precedent scan, and a written path that maps risk, cost, and likely outcomes.",
    },
    {
        "title": "Drafting & negotiation",
        "text": "Documents and correspondence move through version control — you always know what changed and why.",
    },
    {
        "title": "Review & sign-off",
        "text": "Client read-back, defined authorizations, and execution steps that match your internal approvals.",
    },
    {
        "title": "Close-out",
        "text": "Final package, filing reminders if applicable, and archived advice you can retrieve without digging through email.",
    },
)
_PROCESS_STEPS_MARKETING: tuple[dict[str, str], ...] = (
    {"title": "Discovery", "text": "Analytics access, crawl data, and stakeholder interviews so priorities match revenue, not noise."},
    {"title": "Technical & content plan", "text": "Schema, CWV targets, and a brief queue tied to intent — not a generic editorial calendar."},
    {"title": "Build & implement", "text": "Shipped changes in staging first; validation before anything touches production."},
    {"title": "Measure & review", "text": "Dashboards your finance team recognizes; we interpret variance, not vanity."},
    {"title": "Iterate & handoff", "text": "Roadmap for the next quarter, owners named, and documentation the next vendor can read."},
)
_PROCESS_STEPS_PROFESSIONAL: tuple[dict[str, str], ...] = (
    {"title": "Discovery", "text": "We align on goals, constraints, success criteria, and timeline before locking scope."},
    {"title": "Plan & alignment", "text": "Written milestones, single-threaded ownership on our side, and shared assumptions."},
    {"title": "Deliver", "text": "Work proceeds with checkpoints you can verify — not status theatre."},
    {"title": "Walkthrough", "text": "We review deliverables together, capture feedback, and adjust scope only in writing."},
    {"title": "Close-out", "text": "Final artifacts, lessons learned, and next steps bundled so your team can operate without us."},
)
_PROCESS_STEPS_CLEANING: tuple[dict[str, str], ...] = (
    {"title": "Intake", "text": "Walkthrough, hours of access, SDS requirements, and a named facility contact."},
    {"title": "Route planning", "text": "Crew size, chemistry choices per surface, and blackout windows baked into the schedule."},
    {"title": "Service execution", "text": "Checklist-driven visits with photo logs where your program requires proof."},
    {"title": "QA walkthrough", "text": "Spot checks with your lead; punch items logged with dates."},
    {"title": "Close-out", "text": "Visit logs, supply notes, and the next cycle’s calendar confirmed."},
)


def _process_steps_for_vertical(vertical_id: str) -> list[dict[str, str]]:
    v = (vertical_id or "").strip()
    if v == "accounting":
        return [dict(x) for x in _PROCESS_STEPS_ACCOUNTING]
    if v == "legal":
        return [dict(x) for x in _PROCESS_STEPS_LEGAL]
    if v == "marketing_agency":
        return [dict(x) for x in _PROCESS_STEPS_MARKETING]
    if v == "cleaning":
        return [dict(x) for x in _PROCESS_STEPS_CLEANING]
    if v in _TRADES_VERTICALS:
        return [dict(x) for x in _PROCESS_STEPS_TRADES]
    return [dict(x) for x in _PROCESS_STEPS_PROFESSIONAL]


_INDUSTRIES_SERVED_POOLS: dict[str, list[tuple[str, str]]] = {
    "accounting": [
        ("Oil & gas services", "Joint-interest billings, PST/GST on field costs, and year-end accruals crews expect fast."),
        ("Construction & trades", "Job costing, progress billings, holdbacks, and T5018-ready subcontractor tracking."),
        ("Real estate & property", "Rental schedules, capital improvements vs repairs, and trust-account hygiene."),
        ("Professional services firms", "WIP, partner draws, HST/GST on fees, and clean month-end for tax instalments."),
        ("Non-profits & associations", "Restricted funds, grant reporting, and board-ready statements without last-minute panic."),
        ("E-commerce & retail", "Inventory cuts, platform payouts, sales tax nexus questions, and margin you can defend."),
    ],
    "legal": [
        ("Growth-stage companies", "Cap tables, commercial contracts, and employment policies that scale with headcount."),
        ("Real estate & leasing", "Purchase/sale timelines, landlord-tenant risk, and documentation lenders accept."),
        ("Regulated industries", "Compliance calendars, record retention, and counsel that speaks regulator language."),
        ("Family & estates", "Clear mandates, disclosure discipline, and plans that survive a challenge."),
        ("Litigation-exposed businesses", "Incident response, preservation, and early case assessment before positions harden."),
        ("Professional partnerships", "Partner exits, restrictive covenants, and governance that matches your LLP structure."),
    ],
    "medical": [
        ("Family practice & clinics", "Scheduling density, recall workflows, and documentation that survives audit."),
        ("Allied health", "Referral loops, insurer rules, and charting that protects clinicians and patients."),
        ("Specialist groups", "Complex authorizations, OR block time, and revenue cycle handoffs."),
        ("Employer health programs", "Occupational visits, privacy walls, and reporting employers actually use."),
    ],
    "dental": [
        ("Family & pediatric", "Recall systems, hygiene capacity, and parents who need clear cost estimates."),
        ("Cosmetic & restorative", "Treatment sequencing, lab coordination, and financing conversations done right."),
        ("Multi-chair practices", "Sterilization traceability, instrument par levels, and staff cross-training."),
    ],
    "real_estate": [
        ("Residential buyers & sellers", "Offer strategy, inspection leverage, and closing dates that protect deposits."),
        ("Investors & landlords", "Cash-on-cash clarity, tenant law guardrails, and portfolio-level decisions."),
        ("New construction", "Upgrade schedules, deficiency walks, and builder correspondence you can cite later."),
        ("Relocating professionals", "Compressed timelines, virtual showings, and school-district trade-offs."),
    ],
    "marketing_agency": [
        ("B2B SaaS", "Long sales cycles, demo-rich sites, and attribution that survives CFO questions."),
        ("Local services", "Map pack competition, call tracking, and landing pages that match how people search."),
        ("E-commerce", "Feed hygiene, CWV on PLPs, and promo calendars that do not tank organic."),
        ("Professional firms", "Ethical search claims, practice-area silos, and content lawyers will approve."),
    ],
    "news": [
        ("Readers & subscribers", "Explainers, corrections policy, and briefings that respect attention spans."),
        ("Policy-curious professionals", "Primary documents, named sourcing, and timelines that hold up in debate."),
        ("Local communities", "City hall, schools, and infrastructure stories with named officials and dates."),
    ],
    "cleaning": [
        ("Retail & hospitality", "High-traffic floors, seasonal spikes, and guest-facing standards."),
        ("Professional offices", "Quiet hours, vendor coordination, and discreet crews."),
        ("Healthcare-adjacent", "Stricter documentation and careful chemistry choices."),
        ("Education", "Term-time constraints and holiday deep-work blocks."),
        ("Light industrial", "Larger footprints, PPE, and predictable shutdown windows."),
        ("Residential", "Move-in/move-out windows and landlord coordination."),
    ],
    "consulting": [
        ("Energy & infrastructure", "Capital projects, staged gates, and board-ready risk registers."),
        ("Technology implementations", "Change management, vendor scorecards, and benefits tracking past go-live."),
        ("Public-sector programs", "Procurement rules, disclosure rhythms, and audit trails that satisfy reviewers."),
        ("Mid-market operators", "Margin diagnostics, KPI trees, and workshops that produce decisions, not decks."),
        ("Private equity portcos", "100-day plans, synergy tracking, and integration playbooks that hold under diligence."),
        ("Professional partnerships", "Partner compensation models, practice economics, and governance cadence."),
    ],
    "pest_control": [
        ("Food service & hospitality", "Kitchen gaps, dock doors, and dry storage — bait stations and exclusion without disrupting service."),
        ("Multifamily residential", "Common areas, utility chases, and tenant turnover units with documented treatment notices."),
        ("Warehousing & logistics", "Loading docks, pallet storage, and perimeter programs where rodents travel along fence lines."),
        ("Healthcare & clinics", "Low-odor protocols, documentation for facility managers, and schedules that avoid patient hours."),
        ("Schools & childcare", "Vacation-window treatments, notification templates, and IPM plans auditors can follow."),
        ("Office & retail", "Perimeter monitoring, discreet interior placements, and follow-ups tied to seasonal pressure."),
    ],
    "cafe_restaurant": [
        ("Small plates & starters", "Shared dishes paced for the table — not a race to the entrée."),
        ("Mains & grill", "Proteins cooked to temp with sides that change when the market does."),
        ("Vegetable-forward", "Salads and mains built around what’s crisp this week, not last month’s spec."),
        ("Pasta & grains", "Handmade or sourced shapes with sauces that reduce overnight, not from a bag."),
        ("Desserts", "A short list that rotates — pastry picks up where the savory menu leaves off."),
        ("Wine & NA", "Pairings that respect the check and zero-proof options guests actually finish."),
        ("Brunch & daytime", "Eggs, baked goods, and coffee service when the room moves at a different speed."),
    ],
}

_INDUSTRIES_SERVED_FALLBACK: list[tuple[str, str]] = [
    ("Retail & hospitality", "High-traffic floors, seasonal spikes, and guest-facing standards."),
    ("Professional offices", "Quiet hours, vendor coordination, and discreet crews."),
    ("Residential", "Move-in/move-out windows and landlord coordination."),
    ("Healthcare-adjacent", "Stricter documentation and careful chemistry choices."),
    ("Light industrial", "Larger footprints, PPE, and predictable shutdown windows."),
    ("Education", "Term-time constraints and holiday deep-work blocks."),
]


def _industries_served_pool(vertical_id: str) -> list[tuple[str, str]]:
    v = (vertical_id or "").strip()
    pool = _INDUSTRIES_SERVED_POOLS.get(v)
    if pool is not None:
        return list(pool)
    if v in _TRADES_VERTICALS:
        return [
            ("Commercial facilities", "Scheduled access, documented applications, and routes that do not surprise tenants."),
            ("Residential builders", "Pre-occupancy treatments, warranty callbacks, and handoff notes for property managers."),
            ("Property managers", "Service logs, seasonal perimeter work, and escalation when activity spikes between visits."),
            ("Retail & logistics", "Dock and receiving doors, storage rooms, and exterior bait stations along loading lanes."),
            ("Light industrial", "Footprint mapping, exterior pressure points, and follow-ups after weather shifts."),
            ("Institutional sites", "Bid discipline, background checks, and paperwork procurement expects."),
        ]
    return list(_INDUSTRIES_SERVED_FALLBACK)


def _process_page_intro_for_vertical(vertical_id: str, activity: str) -> str:
    v = (vertical_id or "").strip()
    if v == "accounting":
        return (
            f"We run {activity} with filing deadlines, reconciliations, and CRA-facing work documented the same way every month."
        )
    if v == "legal":
        return f"We keep {activity} matters organized: clear instructions, written risk calls, and files you can hand to counsel or auditors."
    if v == "marketing_agency":
        return f"We ship {activity} work with staging, measurement, and changelogs — so results survive the next hire or agency change."
    if v in _TRADES_VERTICALS or v == "cleaning":
        return f"We keep {activity} delivery repeatable on-site: fewer surprises, faster decisions, accountable crews."
    return f"We keep {activity} delivery predictable: written scope, named owners, and checkpoints you can verify."


def _pricing_page_and_tiers(
    vertical_id: str,
    activity: str,
    rng: random.Random,
    country: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Vertical-appropriate pricing labels (avoid SaaS Starter/Standard/Plus for professions)."""
    vid = (vertical_id or "").strip()
    ctry = country or ""

    def _money(opts: list[str]) -> str:
        return localize_money_labels(rng.choice(opts), ctry)

    if vid == "legal":
        header = "How engagements are structured"
        intro = (
            f"Legal fees follow scope and risk — these tiers describe typical starting points for {activity} "
            "before we confirm a written retainer or budget cap."
        )
        tiers = [
            {
                "name": "Initial consultation",
                "price_hint": _money(["From $350", "From $495", "Fixed consult block"]),
                "blurb": "Conflict check, issue spotting, and a clear read on next steps.",
                "features": ["Written summary of options", "Rough budget range", "Timeline to decision"],
            },
            {
                "name": "Defined engagement",
                "price_hint": _money(["From $4.5k", "From $7.2k", "Milestone billing"]),
                "blurb": "Document work, negotiations, or a discrete court or filing package with agreed deliverables.",
                "features": ["Written scope letter", "Named lawyer owner", "Scheduled milestones"],
            },
            {
                "name": "Ongoing counsel",
                "price_hint": _money(["Monthly retainer", "Hourly with cap", "Call for estimate"]),
                "blurb": "For recurring advice, portfolio matters, or steady deal flow.",
                "features": ["Priority access", "Quarterly risk review", "Coordination with in-house"],
            },
        ]
        return header, intro, tiers

    if vid == "accounting":
        header = "Service packages"
        intro = (
            f"Bookkeeping and tax work is priced from scope and volume — use these packages to orient before we finalize {activity} fees."
        )
        tiers = [
            {
                "name": "Bookkeeping support",
                "price_hint": _money(["From $420/mo", "From $680/mo", "Custom"]),
                "blurb": "Reconciliations, AP/AR hygiene, and month-end close support.",
                "features": ["Chart of accounts cleanup", "Bank and card recs", "Management reports"],
            },
            {
                "name": "Compliance & filings",
                "price_hint": _money(["From $2.8k/year", "From $4.2k/year", "Per return"]),
                "blurb": "GST, payroll remittances, T-slips, and year-end corporate or personal filings.",
                "features": ["Filing calendar", "CRA correspondence handling", "T2 or T1 package"],
            },
            {
                "name": "Advisory block",
                "price_hint": _money(["From $1.8k", "Quarterly retainer", "CFO hours pack"]),
                "blurb": "Planning, tax projections, and owner pay/dividend strategy.",
                "features": ["Scenario modeling", "Year-end planning session", "Coordination with your banker"],
            },
        ]
        return header, intro, tiers

    if vid in ("medical", "dental"):
        header = "Care options"
        intro = f"Clinical care is individualized — these levels describe how most patients begin {activity} at our practice."
        tiers = [
            {
                "name": "New patient visit",
                "price_hint": _money(["From $120", "From $165", "Insurance may apply"]),
                "blurb": "History, exam, and a written plan you can follow.",
                "features": ["Clinical assessment", "Treatment options explained", "Next-visit scheduling"],
            },
            {
                "name": "Treatment plan",
                "price_hint": _money(["Plan estimate provided", "Phased payments", "Insurance coordination"]),
                "blurb": "Scoped procedures or therapy blocks with clear milestones.",
                "features": ["Written estimate", "Informed consent", "Progress checkpoints"],
            },
            {
                "name": "Ongoing care",
                "price_hint": _money(["Per visit", "Maintenance package", "Call for rates"]),
                "blurb": "Recall visits, adjustments, or follow-up care on a predictable rhythm.",
                "features": ["Recall reminders", "Same-team continuity", "After-hours guidance line"],
            },
        ]
        return header, intro, tiers

    if vid == "consulting":
        header = "Project tiers"
        intro = f"Consulting work is scoped before kickoff — these tiers help you compare {activity} options before we lock a statement of work."
        tiers = [
            {
                "name": "Discovery sprint",
                "price_hint": _money(["From $4.8k", "From $7.5k", "Two-week block"]),
                "blurb": "Interviews, data pulls, and a prioritized findings memo.",
                "features": ["Stakeholder sessions", "Baseline metrics", "Decision workshop"],
            },
            {
                "name": "Implementation",
                "price_hint": _money(["From $18k", "From $32k", "Milestone-based"]),
                "blurb": "Roadmap execution with weekly steering and documented decisions.",
                "features": ["Workstream owners", "Risk log", "Steering readouts"],
            },
            {
                "name": "Retained advisor",
                "price_hint": _money(["Monthly retainer", "Quarterly advisory", "Call for scope"]),
                "blurb": "Ongoing access for leadership and board cadence.",
                "features": ["Office hours", "Quarterly strategy review", "Vendor coordination"],
            },
        ]
        return header, intro, tiers

    header = "Plans & starting points"
    intro = f"Every {activity} scope is a little different — these tiers help you orient before we confirm details."
    tiers = [
        {
            "name": "Starter",
            "price_hint": _money(["From $890", "From $1.2k", "Custom quote"]),
            "blurb": "Ideal for short engagements and tight scopes.",
            "features": ["Single point of contact", "Written scope", "One revision round"],
        },
        {
            "name": "Standard",
            "price_hint": _money(["From $3.8k", "From $5.5k", "Project-based"]),
            "blurb": "Most teams land here for recurring or multi-phase work.",
            "features": ["Weekly checkpoints", "Documentation pack", "Priority scheduling"],
        },
        {
            "name": "Plus",
            "price_hint": _money(["From $9k", "Retainer", "Call for estimate"]),
            "blurb": "For complex sites, multiple stakeholders, or after-hours needs.",
            "features": ["Dedicated lead", "After-hours windows", "Extended support window"],
        },
    ]
    return header, intro, tiers


def _enrich_extended_site_content(merged: dict[str, Any], brand: dict[str, Any], rng: random.Random) -> None:
    name = str(brand.get("brand_name") or "Brand")
    activity = str(merged.get("activity_summary") or "services")
    city = str(brand.get("city") or "").strip()
    ctry = str(brand.get("country") or "").strip()
    zones = brand.get("service_area_zones")
    zone_list = [str(z) for z in zones] if isinstance(zones, list) else []
    merged["content_tone"] = rng.choice(["professional", "friendly", "authoritative", "local"])
    vid_x = str(merged.get("vertical_id") or "").strip()
    trades_like = vid_x in _TRADES_VERTICALS or vid_x in ("dental", "medical", "cleaning")
    merged.setdefault("usp_heading", "Why teams choose us")
    if trades_like:
        merged["usp_heading"] = rng.choice(
            ["Why homeowners call us", "What neighbors notice", "Local crews, accountable work"],
        )
        loc = city or "your area"
        merged["usp_items"] = [
            {
                "title": "Real arrival windows",
                "text": rng.choice(
                    [
                        f"We confirm timing for {loc} and update you if the route shifts.",
                        f"Dispatch confirms windows for {loc} and sends a quick text when traffic or prior jobs move the clock.",
                    ],
                ),
            },
            {
                "title": "Written scope",
                "text": rng.choice(
                    [
                        "Labor, parts, and exclusions are listed before tools come off the truck.",
                        "You see labor, materials, and what we are not covering before we start billing time.",
                    ],
                ),
            },
            {
                "title": "Licensed & insured",
                "text": rng.choice(
                    [
                        "Credentials go to your property contact before the first visit.",
                        "COI and license details hit your inbox before the crew parks.",
                    ],
                ),
            },
            {
                "title": "Same faces",
                "text": rng.choice(
                    [
                        f"You get a steady crew familiar with your building — not a rotating unknown bench.",
                        f"Repeat work in {loc} means the same lead when possible — fewer re-briefs, fewer surprises.",
                    ],
                ),
            },
        ]
    elif vid_x == "cafe_restaurant":
        merged["usp_heading"] = rng.choice(
            ["Why people come back", "What the room feels like", "The usual reasons guests stay"],
        )
        loc_r = city or "the neighborhood"
        merged["usp_items"] = [
            {
                "title": "Seasonal menu rhythm",
                "text": rng.choice(
                    [
                        "We shorten the card when produce peaks, then widen it when suppliers stabilize.",
                        "Specials land when ingredients make sense — not to fill a content calendar.",
                    ],
                ),
            },
            {
                "title": "Kitchen and floor in sync",
                "text": rng.choice(
                    [
                        "Pacing is set so the kitchen can cook to standard when the room is full.",
                        "FOH signals when tables need air; the pass doesn’t guess.",
                    ],
                ),
            },
            {
                "title": "A room you can hear yourself in",
                "text": rng.choice(
                    [
                        "Music and seating tuned for conversation — still lively on Saturday.",
                        "Lighting and spacing aimed at comfort, not just turning covers.",
                    ],
                ),
            },
            {
                "title": "Reservations without the runaround",
                "text": rng.choice(
                    [
                        f"We hold tables for locals who plan ahead — walk-ins when space allows ({loc_r}).",
                        "Clear policy on holds and late arrivals so the night stays fair for everyone.",
                    ],
                ),
            },
        ]
    else:
        if vid_x in ("marketing_agency", "consulting"):
            own_line = rng.choice(
                [
                    "Every scope has a named lead and written handoff so nothing drops between teams.",
                    "One named lead and a written handoff beat a committee inbox when deadlines tighten.",
                ],
            )
        else:
            own_line = rng.choice(
                [
                    "Every scope has a named lead and a written plan so field and office stay aligned.",
                    "Field and office share one written plan with a named owner — no silent drift between teams.",
                ],
            )
        loc2 = city or "your area"
        merged["usp_items"] = [
            {
                "title": "Responsive scheduling",
                "text": rng.choice(
                    [
                        f"We plan around real access and blackout windows in {loc2}.",
                        f"Blackout windows and access rules in {loc2} land on the schedule before we promise dates.",
                    ],
                ),
            },
            {
                "title": "Clear ownership",
                "text": own_line,
            },
            {
                "title": "Proof, not promises",
                "text": rng.choice(
                    [
                        "Checklists, photos on request, and paperwork your auditors can file.",
                        "When auditors ask, the checklist and photos are already in the folder — not reconstructed later.",
                    ],
                ),
            },
            {
                "title": "Local crew",
                "text": rng.choice(
                    [
                        f"The same people answer the phone and show up — based in {city or 'the community'}.",
                        f"Phones and trucks map to the same small team based in {city or 'the community'}.",
                    ],
                ),
            },
        ]
    rng.shuffle(merged["usp_items"])
    merged["usp_items"] = merged["usp_items"][: rng.randint(3, min(6, len(merged["usp_items"])))]
    merged["process_preview_heading"] = "How a typical engagement runs"
    retail_like = vid_x in ("cafe_restaurant", "clothing", "fitness")
    if trades_like:
        _proc_steps = [
            {
                "title": "Site walkthrough",
                "text": "We confirm access, safety, and realistic windows before calendars harden.",
            },
            {
                "title": "Written scope",
                "text": "Labor, parts, and exclusions are listed before tools come off the truck.",
            },
            {
                "title": "Build & verify",
                "text": "Checkpoints you can witness — readings and photos when they matter to sign-off.",
            },
            {
                "title": "Closeout pack",
                "text": "Warranties and paperwork land in one place, not across scattered threads.",
            },
        ]
    elif vid_x in ("marketing_agency", "consulting", "legal", "accounting"):
        _proc_steps = [
            {
                "title": "Intake",
                "text": "Goals, constraints, and stakeholders are named before dates are promised.",
            },
            {
                "title": "Blueprint",
                "text": "Milestones, owners, and review gates arrive in writing — not as implied side notes.",
            },
            {
                "title": "Delivery",
                "text": "We ship against checkpoints you can verify instead of vague status pings.",
            },
            {
                "title": "Review",
                "text": "Lessons feed the next cycle so quality bars do not drift quietly.",
            },
        ]
    elif retail_like:
        _proc_steps = [
            {
                "title": "Listen",
                "text": "We align on timing, capacity, and what good looks like before doors open or carts load.",
            },
            {
                "title": "Plan the week",
                "text": "Prep, staffing, and contingencies are spelled out while things are still calm.",
            },
            {
                "title": "Run & adjust",
                "text": "We adapt in the moment without improvising safety, policy, or guest promises.",
            },
            {
                "title": "Short debrief",
                "text": "One-page notes on what to repeat — and what to fix before the next rush.",
            },
        ]
    else:
        _proc_steps = [
            {"title": "Discovery", "text": "We align on goals, constraints, and timing before locking calendars."},
            {"title": "Plan", "text": "You get a written scope with milestones and a single owner on our side."},
            {"title": "Deliver", "text": "We execute with checkpoints you can verify, not vague status emails."},
            {"title": "Review", "text": "We capture lessons and tune the next cycle so quality holds."},
        ]
    n_steps = rng.randint(3, min(5, len(_proc_steps)))
    start = rng.randint(0, len(_proc_steps) - n_steps)
    merged["process_preview_steps"] = _proc_steps[start : start + n_steps]
    _cta_href = str(merged.get("hero_cta_href") or "contact.php").strip()
    _contact_href = _cta_href if _cta_href.lower().startswith("contact") else "contact.php"
    if vid_x == "cafe_restaurant":
        merged["service_area_list_heading"] = rng.choice(
            ["Visit us", "Hours & location", "Find us", "One address"],
        )
        merged["service_area_list_intro"] = rng.choice(
            [
                f"One dining room in {city} — parking, transit, and hours are on the contact page.",
                f"We’re a single location{f' in {city}' if city else ''}; no franchise map or dispatch zones.",
                "Directions, reservations, and accessibility notes live next to our phone and email.",
            ],
        )
        merged["service_area_links"] = [
            {
                "label": rng.choice(["Contact & directions", "Hours & map", "Visit & reserve"]),
                "href": _contact_href,
            },
        ]
    elif vid_x in _PROF_OFFICE_VERTICALS:
        merged["service_area_list_heading"] = rng.choice(
            ["Offices & jurisdictions", "Where we work", "How to reach us", "Locations"],
        )
        merged["service_area_list_intro"] = rng.choice(
            [
                f"Reach {name} through the contact page{f' — we’re based in {city}' if city else ''}; we do not maintain neighborhood SEO landing pages.",
                "Directions, intake channels, and scheduling live on the contact page — one front door for new matters.",
                f"New client inquiries run through a single intake path{f' for {city}' if city else ''}; no separate ‘area’ microsites.",
            ],
        )
        merged["service_area_links"] = [
            {
                "label": rng.choice(["Contact & intake", "Reach the office", "Schedule a call"]),
                "href": _contact_href,
            },
        ]
    else:
        merged["service_area_list_heading"] = "Areas we cover"
        merged["service_area_list_intro"] = (
            f"We regularly serve clients across these neighborhoods{f' near {city}' if city else ''}."
        )
        hub_rows: list[dict[str, str]] = []
        for z in zone_list or ([city] if city else ["Metro core"]):
            zs = _slugify_ascii(z, max_len=48)
            hub_rows.append({"label": z, "href": f"service-area-{zs}.php"})
        merged["service_area_links"] = hub_rows
    merged["clients_heading"] = "Organizations that rely on us"
    _n_pool = rng.randint(6, 8)
    _site_clients: list[str] = []
    _seen_c: set[str] = set()
    _prefix_used: set[str] = set()
    _guard = 0
    while len(_site_clients) < _n_pool and _guard < 200:
        _guard += 1
        _cand = _fake_client_company(rng)
        _first = (_cand.split()[0] or "").lower()
        if _cand in _seen_c:
            continue
        if _first in _prefix_used:
            continue
        _seen_c.add(_cand)
        _prefix_used.add(_first)
        _site_clients.append(_cand)
    while len(_site_clients) < _n_pool:
        _cand = _fake_client_company(rng)
        if _cand not in _seen_c:
            _seen_c.add(_cand)
            _site_clients.append(_cand)
    merged["site_client_names"] = list(_site_clients)
    _nk = rng.randint(4, min(8, len(_site_clients)))
    merged["client_logos"] = [{"name": _site_clients[i]} for i in range(_nk)]
    vid_proc = str(merged.get("vertical_id") or "").strip()
    ph, pi, ptiers = _pricing_page_and_tiers(vid_proc, activity, rng, ctry)
    merged["pricing_page_header"] = ph
    merged["pricing_page_intro"] = pi
    merged["pricing_tiers"] = ptiers
    rng.shuffle(merged["pricing_tiers"])
    merged["process_page_header"] = "Our process, end to end"
    merged["process_page_intro"] = _process_page_intro_for_vertical(vid_proc, activity)
    merged["process_steps_items"] = _process_steps_for_vertical(vid_proc)
    if vid_proc in _PROF_OFFICE_VERTICALS:
        merged["portfolio_page_header"] = "Representative matters"
        merged["portfolio_page_intro"] = (
            f"Illustrative engagements consistent with how {name} practices — identifiers anonymized where required."
        )
        merged["portfolio_items"] = []
        for _pi in range(rng.randint(2, 3)):
            merged["portfolio_items"].append(
                {
                    "title": rng.choice(
                        [
                            "Commercial contract advisory",
                            "Regulatory response and filings",
                            "Transaction support under time pressure",
                            "Governance memo for the board",
                            "Workforce policy refresh",
                        ],
                    ),
                    "summary": rng.choice(
                        [
                            "Scoped issues early, aligned on written assumptions, and kept spend tied to outcomes.",
                            "Delivered board-ready documentation within the review window the client set.",
                            "Reduced escalation risk by agreeing documentation standards with counterpart counsel.",
                            "Mapped obligations across jurisdictions before signatures, not after a surprise request.",
                        ],
                    ),
                    "image_src": "",
                },
            )
    else:
        merged["portfolio_page_header"] = "Recent work"
        merged["portfolio_page_intro"] = f"A sample of {activity} projects we can share publicly."
        merged["portfolio_items"] = []
        for idx in range(4):
            merged["portfolio_items"].append(
                {
                    "title": rng.choice(
                        ["Interior refresh", "Seasonal program", "Full build-out", "Rapid turnaround", "Multi-site"],
                    ),
                    "summary": rng.choice(
                        [
                            "Delivered on schedule with weekly check-ins and clear documentation.",
                            "Weekly photos and written sign-offs kept stakeholders aligned without extra meetings.",
                            "Scope held steady; changes stayed rare and always written.",
                            "Milestones matched the plan auditors saw — not a retrofitted timeline.",
                        ],
                    ),
                    "image_src": f"img/portfolio/p-{idx + 1:02d}.jpg",
                },
            )
    merged["case_studies_page_header"] = "Case studies"
    merged["case_studies_page_intro"] = "Challenges, constraints, and what changed after we got involved."
    n_cs = rng.randint(2, 4)
    merged["case_studies"] = []
    seen_case_slugs: set[str] = set()
    activity_slug = _slugify_ascii(activity, max_len=24) or "engagement"
    _clients_pool: list[str] = list(merged.get("site_client_names") or [])
    for _k in range(n_cs):
        district = rng.choice(zone_list) if zone_list else (city or "metro-core")
        dslug = _slugify_ascii(district, max_len=28) or "local"
        if vid_proc in _PROF_OFFICE_VERTICALS:
            proj_seed = rng.choice(
                [
                    f"matter-{activity_slug}",
                    f"advisory-{activity_slug}",
                    f"engagement-{activity_slug}",
                    f"retainer-{activity_slug}",
                ],
            )
            base_cs = _slugify_ascii(f"{proj_seed}-{dslug}", max_len=48).strip("-") or f"matter-{dslug}"
            slug = _unique_slug_in_set(base_cs, seen_case_slugs, max_len=52)
            seen_case_slugs.add(slug)
            client = rng.choice(_clients_pool) if _clients_pool else _fake_client_company(rng)
            client_type_lbl = rng.choice(
                [
                    "Regulated employer",
                    "Family-owned business",
                    "Professional partnership",
                    "Not-for-profit board",
                    "Growth-stage company",
                ],
            )
            duration_lbl = rng.choice(
                [
                    "12-week advisory window",
                    "90-day remediation plan",
                    "Six-month retainer cycle",
                    "Quarterly board cadence",
                    "Eight-week diligence sprint",
                ],
            )
            project_title = rng.choice(
                [
                    "Governance cleanup before a capital raise",
                    "Contract dispute containment without trial",
                    "Policy refresh after regulatory guidance shifted",
                    "Cross-border setup with cautious pacing",
                    "Workforce restructure with defensible documentation",
                ],
            )
            cs_summary = rng.choice(
                [
                    (
                        f"{name} supported a {client_type_lbl.lower()} client in {district} — "
                        f"{duration_lbl.lower()} with written scope, risk notes, and clear decision points."
                    ),
                    (
                        f"A {activity} matter in {district}: {duration_lbl.lower()}, "
                        "single relationship partner, and documentation the board could rely on."
                    ),
                ],
            )
            chal = rng.choice(
                [
                    (
                        f"The {client_type_lbl.lower()} client faced overlapping deadlines in {district} "
                        "and needed advice that could move without burying judgment in email threads."
                    ),
                    (
                        "Counterpart counsel pressed for fast signatures; internal stakeholders still needed "
                        "plain-language risk framing before committing."
                    ),
                ],
            )
            sol = rng.choice(
                [
                    (
                        f"{name} issued short, dated risk memos, staged sign-offs against a written checklist, "
                        "and kept one lead attorney accountable for scope."
                    ),
                    (
                        f"{name} aligned the client team on assumptions first, then drafted against those assumptions "
                        f"so review cycles in {district} stayed predictable."
                    ),
                ],
            )
            results_html = (
                "<ul><li>Scoped contentious issues early so spend tracked to outcomes, not motion practice.</li>"
                "<li>Delivered board-ready documentation inside the agreed review window.</li>"
                "<li>Reduced escalation risk by documenting advice where the client could find it later.</li></ul>"
            )
        else:
            proj_seed = rng.choice(
                [
                    f"{activity_slug}-rollout",
                    f"{activity_slug}-retrofit",
                    f"{activity_slug}-program",
                    f"{activity_slug}-restoration",
                    f"multi-phase-{activity_slug}",
                    f"urgent-{activity_slug}",
                ],
            )
            base_cs = _slugify_ascii(f"{proj_seed}-{dslug}", max_len=48).strip("-") or f"project-{dslug}"
            slug = _unique_slug_in_set(base_cs, seen_case_slugs, max_len=52)
            seen_case_slugs.add(slug)
            client = rng.choice(_clients_pool) if _clients_pool else _fake_client_company(rng)
            client_type_lbl = rng.choice(
                ["Commercial", "Industrial", "Multi-family residential", "Municipal", "Private residential"],
            )
            duration_lbl = rng.choice(
                [
                    "72-hour emergency stabilization",
                    "10-day mobilization",
                    "6-week phased program",
                    "Seasonal maintenance cycle",
                    "4-month capital rollout",
                ],
            )
            project_title = rng.choice(
                [
                    "Mechanical retrofit without a full shutdown",
                    "Rooftop reliability after repeat failures",
                    "Controls upgrade with documented commissioning",
                    "Capacity expansion ahead of lease renewal",
                    "Seasonal readiness under audit pressure",
                ],
            )
            cs_summary = rng.choice(
                [
                    (
                        f"A {activity} engagement in {district} for a {client_type_lbl.lower()} client — "
                        f"{duration_lbl.lower()}, documented handoffs, and measurable outcomes."
                    ),
                    (
                        f"Three similar requests stacked around {district} one busy season; {name} sequenced crews "
                        f"so nobody lost their access window — {duration_lbl.lower()} end to end."
                    ),
                    (
                        f"{client_type_lbl} operations in {district} needed {activity} without pausing the floor — "
                        f"{duration_lbl.lower()}, with paperwork the facilities lead could file as-is."
                    ),
                ],
            )
            chal = rng.choice(
                [
                    (
                        f"The {client_type_lbl.lower()} client needed reliable {activity} coverage in {district} "
                        "without shutting down daily operations or breaking compliance trails."
                    ),
                    (
                        f"Traffic patterns and loading rules in {district} made same-day heroics unrealistic; "
                        f"the {client_type_lbl.lower()} client still needed predictable {activity} coverage."
                    ),
                ],
            )
            sol = rng.choice(
                [
                    (
                        f"{name} staged work in windows that matched their traffic patterns, "
                        "assigned a single operations lead, and logged verification steps the facilities team could audit."
                    ),
                    (
                        f"{name} matched shifts to quiet hours in {district}, named one operations lead, "
                        "and photographed checkpoints the client could drop into their own QA binder."
                    ),
                ],
            )
            results_html = (
                "<ul><li>Cut repeat scheduling conflicts by roughly 40% in the first quarter.</li>"
                "<li>Passed internal QA checks with zero major findings on the last two walkthroughs.</li>"
                "<li>Maintained the same crew lead for continuity.</li></ul>"
            )
        merged["case_studies"].append(
            {
                "slug": slug,
                "project_title": project_title,
                "district": district,
                "client_type": client_type_lbl,
                "duration": duration_lbl,
                "title": f"{client}: {project_title.lower()}",
                "summary": cs_summary,
                "client_label": client,
                "challenge": chal,
                "solution": sol,
                "results_html": results_html,
            },
        )
    merged["careers_page_header"] = "Careers"
    vid_careers = str(merged.get("vertical_id") or "").strip()
    _careers_intros = {
        "legal": (
            "We hire for judgment, writing discipline, and the habits that earn client trust.",
            "We look for careful research, ethical instincts, and calm communication under deadline.",
        ),
        "accounting": (
            "We hire for accuracy, discretion, and the discipline to keep files audit-clear.",
            "We value people who treat deadlines and reconciliations as non-negotiable quality bars.",
        ),
        "consulting": (
            "We hire for structured thinking, client empathy, and ownership through messy phases.",
            "We want consultants who write clearly, challenge assumptions politely, and finish what they start.",
        ),
        "marketing_agency": (
            "We hire for curiosity, craft, and the patience to prove impact with data — not slides alone.",
            "We look for channel depth, editorial judgment, and calm coordination when campaigns get loud.",
        ),
        "news": (
            "We hire for skepticism, speed with verification, and respect for readers’ time.",
            "We want reporters and editors who fix mistakes loudly and source claims quietly.",
        ),
        "cafe_restaurant": (
            "We hire for pace, palate, and the professionalism guests feel on busy nights.",
            "We value kitchen discipline, FOH empathy, and people who protect the room’s tone.",
        ),
        "fitness": (
            "We hire for coaching standards, member safety, and consistency on the floor.",
            "We want people who model movement quality, enforce etiquette, and welcome beginners honestly.",
        ),
        "clothing": (
            "We hire for detail, customer empathy, and reliable execution when volumes spike.",
            "We value clear communication across e-com, studio, and fulfillment — without blame when things break.",
        ),
        "dental": (
            "We hire for clinical care, infection-control habits, and calm patient communication.",
            "We look for licensed discipline where required, teamwork at the chair, and front-desk warmth.",
        ),
        "medical": (
            "We hire for protocol, privacy, and the patience to guide patients through stressful moments.",
            "We value clinical support staff who document carefully and treat schedules as patient care.",
        ),
        "real_estate": (
            "We hire for market honesty, negotiation discipline, and paperwork you can defend.",
            "We want agents and coordinators who protect clients’ timelines — not just commission milestones.",
        ),
    }
    fam_intro = _careers_copy_family(vid_careers)
    if fam_intro == "trades":
        merged["careers_page_intro"] = rng.choice(
            (
                "We hire for safety habits, reliability, and clear communication on-site.",
                "We look for people who show up prepared, respect the crew, and document what the client needs.",
            ),
        )
    else:
        merged["careers_page_intro"] = rng.choice(
            _careers_intros.get(
                vid_careers,
                (
                    "We hire for judgment, communication, and showing up when it matters.",
                    "We value ownership, clear handoffs, and standards teammates can rely on.",
                ),
            ),
        )
    role_pool = list(_careers_role_pool(vid_careers))
    rng.shuffle(role_pool)
    n_open = rng.randint(2, min(4, len(role_pool)))
    merged["careers_openings"] = []
    for r in role_pool[:n_open]:
        merged["careers_openings"].append(
            {
                "slug": _slugify_ascii(r, max_len=24),
                "title": r,
                "location": city or rng.choice(["Hybrid", "On-site", "Local"]),
                "type": rng.choice(["Full-time", "Full-time", "Contract-to-hire", "Part-time"]),
                "blurb": _careers_opening_blurb(
                    r, name=name, activity=activity, city=city, rng=rng, vertical_id=vid_careers
                ),
            },
        )
    vid_ind = str(merged.get("vertical_id") or "").strip()
    if vid_ind == "cafe_restaurant":
        merged["industries_page_header"] = rng.choice(
            ["Menu", "What we’re cooking", "The menu", "Food & drink"],
        )
        merged["industries_page_intro"] = rng.choice(
            [
                f"Seasonal picks and staples — the kitchen shortens the card when produce peaks, then opens it back up.",
                f"Dishes we can execute consistently on a Friday night, with room for weekly specials.",
                f"Same room, shifting plates: winter roots, summer herbs, and the sauces that tie it together.",
            ],
        )
    else:
        merged["industries_page_header"] = "Industries we serve"
        if vid_ind == "accounting":
            merged["industries_page_intro"] = (
                "Alberta and federal filing rules shift by industry — we keep sector-specific checklists so nothing ships late."
            )
        elif vid_ind == "legal":
            merged["industries_page_intro"] = "We match counsel depth to sector risk — same rigor, different fact patterns."
        elif vid_ind == "pest_control":
            merged["industries_page_header"] = rng.choice(
                ["Markets we serve", "Who we work with", "Property types & programs"],
            )
            merged["industries_page_intro"] = rng.choice(
                [
                    "Different buildings mean different pest pressure — we tune monitoring, products, and visit cadence to the site.",
                    "Kitchens, warehouses, and multifamily sites each get a plan that matches how people move through the space.",
                    "We group clients by risk profile and seasonality so technicians arrive with the right tools and paperwork.",
                ],
            )
        else:
            merged["industries_page_intro"] = "We adapt playbooks by sector while keeping the same accountability model."
    ind_pool = _industries_served_pool(vid_ind)
    rng.shuffle(ind_pool)
    hi = min(6, len(ind_pool))
    lo = min(4, hi) if hi else 1
    n_ind = rng.randint(lo, hi) if hi else 0
    merged["industries_served_items"] = [{"name": a, "description": b} for a, b in ind_pool[:n_ind]]
    merged["resources_page_header"] = "Resources"
    merged.setdefault(
        "resources_page_intro",
        "Third-party references we point clients to when they want deeper reading.",
    )
    srcs = _pick_sources(rng, str(merged.get("vertical_id") or ""), 6)
    merged["resource_links"] = [{"title": s["title"], "url": s["url"], "note": s["org"]} for s in srcs]
    if vid_ind == "cafe_restaurant":
        merged["service_areas_page_header"] = rng.choice(
            ["Visit us", "Location & hours", "Find the dining room"],
        )
        merged["service_areas_page_intro"] = rng.choice(
            [
                f"One address in {city or 'town'} — parking, transit, and reservations on the contact page.",
                "We’re a single dining room, not a service map. Directions and hours live with our phone number.",
                "No district landing pages — just the restaurant, the hours, and how to book.",
            ],
        )
    else:
        merged["service_areas_page_header"] = "Service areas"
        merged["service_areas_page_intro"] = (
            f"Local routes and crews organized around {city or 'core neighborhoods'} — tap a district for more detail."
        )
    merged.setdefault(
        "mission_statement",
        f"{name} exists to make {activity} predictable for the people responsible for outcomes.",
    )
    merged.setdefault(
        "core_values",
        [
            "Tell the truth early when dates slip",
            "One owner per engagement",
            "Paperwork you can file without translation",
        ],
    )
    fy_raw = brand.get("founded_year")
    cy = as_of_year(brand)
    merged["about_timeline"] = []
    if fy_raw and str(fy_raw).strip().isdigit():
        merged["about_timeline"] = _build_about_timeline_rows(
            name, int(fy_raw), cy, rng, vertical_id=str(merged.get("vertical_id") or "")
        )
    svc_items = merged.get("service_items")
    vid_svc = str(merged.get("vertical_id") or "").strip()
    trades_svc = vid_svc in _TRADES_VERTICALS or vid_svc in ("dental", "medical", "cleaning", "fitness")
    agency_svc = vid_svc in ("marketing_agency", "consulting")
    if isinstance(svc_items, list):
        for si, it in enumerate(svc_items):
            if not isinstance(it, dict):
                continue
            if not (it.get("ideal_for") or "").strip():
                if trades_svc:
                    it["ideal_for"] = rng.choice(
                        [
                            "Property owners who want the problem fixed once, not revisited every season.",
                            "Facilities teams that need paperwork and access rules respected on site.",
                            "Anyone who wants pricing explained before work starts, not after the invoice.",
                        ],
                    )
                elif agency_svc:
                    it["ideal_for"] = rng.choice(
                        [
                            "Teams that need predictable scheduling and one accountable lead.",
                            "Operators who care about documentation and audit-ready checklists.",
                            "Owners juggling multiple locations and tight communication loops.",
                        ],
                    )
                else:
                    it["ideal_for"] = rng.choice(
                        [
                            "Organizations that want clear dates and one accountable point of contact.",
                            "Leaders who need documentation they can share with finance or compliance.",
                            "Busy sites that cannot afford vague scopes or surprise add-ons.",
                        ],
                    )
            if not (it.get("pricing_hint") or "").strip():
                if trades_svc:
                    it["pricing_hint"] = rng.choice(
                        [
                            "Call for a written estimate",
                            "Typical visit scoped on site before billing",
                            "Flat dispatch fee plus labor — quoted upfront",
                        ],
                    )
                elif agency_svc:
                    it["pricing_hint"] = rng.choice(
                        ["Call for a tailored quote", "Starts from a short discovery block", "Scoped after walkthrough"],
                    )
                else:
                    it["pricing_hint"] = rng.choice(
                        [
                            "Call for a tailored quote",
                            "Scoped after a short consultation",
                            "Written estimate before work begins",
                        ],
                    )
            steps = it.get("process_steps")
            if not isinstance(steps, list) or not steps:
                it["process_steps"] = _service_process_steps_for_item(it, activity, city, si)
            if not it.get("service_faq"):
                tit = str(it.get("title") or "service").lower()
                loc_svc = f" in {city}" if city else ""
                faq_sets = [
                    [
                        {
                            "q": f"How long does a typical {tit} visit take?",
                            "a": rng.choice(
                                [
                                    "Most first visits are scoped after a short walkthrough; duration depends on access and size.",
                                    "We quote time after a quick walkthrough — access, parking, and building rules move the clock more than square footage.",
                                ],
                            ),
                        },
                        {
                            "q": "Do you provide estimates in writing?",
                            "a": rng.choice(
                                [
                                    "Yes — you’ll get scope, assumptions, and exclusions before work begins.",
                                    "Written scope lands before billing time: what’s included, what isn’t, and what could change it.",
                                ],
                            ),
                        },
                    ],
                    [
                        {
                            "q": f"What should we prep before a {tit} appointment?",
                            "a": rng.choice(
                                [
                                    "Clear access paths, a single point of contact on site, and any prior reports you want us to factor in.",
                                    "Have someone available to unlock common areas and confirm where we can stage tools — it saves the first hour.",
                                ],
                            ),
                        },
                        {
                            "q": f"Do you serve {city or 'our area'} regularly for {tit}?",
                            "a": rng.choice(
                                [
                                    f"Yes — routes and crews run through {city or 'the area'} weekly; dispatch confirms windows{loc_svc}.",
                                    f"We schedule {city or 'local'} work in batches where it helps; you’ll see realistic windows, not fantasy ETAs.",
                                ],
                            ),
                        },
                    ],
                    [
                        {
                            "q": f"Can {tit} be scheduled after hours?",
                            "a": rng.choice(
                                [
                                    "Often yes — building rules and escort requirements decide what’s realistic.",
                                    "After-hours is common when access is easier; we confirm badging and escorts before we book.",
                                ],
                            ),
                        },
                        {
                            "q": "How do change orders work?",
                            "a": rng.choice(
                                [
                                    "Anything outside the written scope gets a short addendum before more labor or materials.",
                                    "We pause, write the delta, and only continue once both sides sign off — no surprise line items.",
                                ],
                            ),
                        },
                    ],
                ]
                it["service_faq"] = rng.choice(faq_sets)
    _enrich_testimonial_items(merged, brand, rng)
    _enrich_hero_footer_trust(merged, brand, rng)


def fill_content(
    rng: random.Random,
    brand: dict[str, Any],
    data_dir: Path,
    vertical: dict[str, Any] | None = None,
    theme_pack: dict[str, Any] | None = None,
    news_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    v = vertical
    if v is None:
        v = pick_vertical(rng, None, load_verticals(data_dir))
    name = str(brand.get("brand_name", "Brand"))

    hero_title = str(v.get("hero_title", "{brand_name}")).format(brand_name=name)
    hero_subtitle = str(v.get("hero_subtitle", "")).format(brand_name=name)
    alts_t = v.get("hero_title_alt")
    alts_s = v.get("hero_subtitle_alt")
    if isinstance(alts_t, list) and alts_t and rng.random() < 0.35:
        hero_title = _coerce_vertical_text(rng.choice(alts_t)).format(brand_name=name)
    if isinstance(alts_s, list) and alts_s and rng.random() < 0.35:
        hero_subtitle = _coerce_vertical_text(rng.choice(alts_s)).format(brand_name=name)

    service_items = v.get("service_items")
    if not isinstance(service_items, list) or len(service_items) < 1:
        service_items = [
            {"title": "Strategy", "text": "Roadmaps, positioning, and prioritization."},
            {"title": "Delivery", "text": "Hands-on execution with clear milestones."},
            {"title": "Support", "text": "Ongoing optimization and reporting."},
        ]

    seo_blurb_raw = v.get("seo_blurb")
    seo_blurb = str(seo_blurb_raw).format(brand_name=name) if seo_blurb_raw else ""

    activity = str(v.get("activity_summary", "its services"))
    vid_key = str(v.get("id") or "")
    cta_label, cta_href = _hero_cta_for_vertical(vid_key, rng)

    base: dict[str, Any] = {
        "hero_title": hero_title,
        "hero_subtitle": hero_subtitle,
        "hero_cta_label": cta_label,
        "hero_cta_href": cta_href,
        "about_page_header": str(v.get("about_page_header", "About us")),
        "about_page_sub": str(v.get("about_page_sub", "")),
        "contact_page_header": str(v.get("contact_page_header", "Contact")),
        "contact_page_sub": str(v.get("contact_page_sub", "")),
        "about_heading": str(v.get("about_heading", "Who we are")),
        "about_body": str(v.get("about_body", "")).format(brand_name=name),
        "services_heading": str(v.get("services_heading", "What we do")),
        "services_intro": str(v.get("services_intro", "")).format(brand_name=name),
        "service_items": service_items,
        "contact_teaser": str(v.get("contact_teaser", "")).format(brand_name=name),
        "vertical_id": v.get("id"),
        "vertical_label": v.get("label_ru"),
        "industry": activity,
        "service": activity,
        "activity_summary": activity,
        "seo_blurb": seo_blurb,
        "vertical_seo_label": _VERTICAL_SEO_LABEL.get(vid_key) or _VERTICAL_SEO_LABEL["generic"],
        "about_services_short_label": _about_services_link_label(vid_key),
    }

    overlay: dict[str, Any] = {}
    if isinstance(theme_pack, dict):
        raw = theme_pack.get("content_overlay")
        if isinstance(raw, dict):
            overlay = raw
    merged = merge_content_overlay(base, overlay, name, activity, brand=brand)
    if isinstance(news_options, dict):
        for k, v in news_options.items():
            if v is not None:
                merged[k] = v
    svc_items = merged.get("service_items")
    if isinstance(svc_items, list):
        _inject_service_pricing(svc_items, vid_key, rng, brand)
        dr, _ = derive_price_range_and_enrich_offers(
            svc_items,
            country=str(brand.get("country") or ""),
            vertical_id=vid_key,
        )
        if dr:
            merged["price_range"] = dr
    _ensure_component_defaults(merged, name, activity, vid_key, brand, rng)
    _ensure_team_items(merged, name, vid_key, brand, rng)
    _append_about_paragraphs(merged, vid_key, rng, brand)
    _prepend_local_story(merged, brand, name, rng)
    merged["about_body"] = _dedupe_similar_sentences(str(merged.get("about_body") or ""))
    _ensure_hero_distinct_from_about(merged, rng)
    _ensure_blog_and_faq_pages(merged, name, activity, rng, vid_key, brand)
    if vid_key == "news":
        enrich_news_vertical_content(merged, brand, rng)
    else:
        enrich_longform_blog_for_non_news(merged, brand, rng)
    if vid_key == "clothing" and not merged.get("products"):
        # Minimal storefront catalog so "clothing" doesn't look like a brochure.
        brand_name = str(brand.get("brand_name") or name)
        ctry = str(brand.get("country") or "").strip()
        if ctry == "Ireland":
            shop_ccy = "EUR"
        elif ctry == "Canada":
            shop_ccy = "CAD"
        else:
            shop_ccy = "USD"
        drops = [
            ("Washed tee", "Cotton jersey", ["XS", "S", "M", "L", "XL"], 36),
            ("Rib tank", "Cotton rib", ["XS", "S", "M", "L"], 28),
            ("Oxford shirt", "Cotton oxford", ["XS", "S", "M", "L", "XL"], 88),
            ("Chore jacket", "Cotton canvas", ["S", "M", "L", "XL"], 148),
            ("Relaxed trouser", "Cotton twill", ["28", "30", "32", "34", "36"], 112),
            ("Knit layer", "Wool blend", ["XS", "S", "M", "L", "XL"], 124),
            ("Wool scarf", "Wool", ["One size"], 54),
            ("Everyday tote", "Heavy canvas", ["One size"], 42),
        ]
        products: list[dict[str, Any]] = []
        for i, (title, material, sizes, price) in enumerate(drops):
            p_title = f"{title}"
            slug = _slugify_ascii(f"{brand_name}-{p_title}", max_len=56)
            color = rng.choice(["Ink", "Sand", "Slate", "Olive", "Oat", "Charcoal"])
            products.append(
                {
                    "title": p_title,
                    "slug": slug,
                    "sku": f"{slug[:10].upper()}-{100 + i}",
                    "price": float(price),
                    "currency": shop_ccy,
                    "color": color,
                    "material": material,
                    "sizes": sizes,
                    "fit_notes": rng.choice(
                        [
                            "True to size. If between sizes, size up for a relaxed fit.",
                            "Relaxed through the body with room to layer.",
                            "Slightly cropped length; check measurements if tall.",
                        ]
                    ),
                    "care": rng.choice(
                        [
                            "Machine wash cold, gentle. Hang dry. Low iron if needed.",
                            "Hand wash cool or dry clean. Dry flat.",
                            "Wash inside-out, cold. Tumble low or hang dry.",
                        ]
                    ),
                    "description": (
                        f"A calm essential built around honest {material.lower()} notes, measured sizing, "
                        f"and a finish meant to look better after repeat wear."
                    ),
                    "image_src": f"img/products/{slug}.jpg",
                    "in_stock": True,
                }
            )
        merged["products"] = products
    _enrich_extended_site_content(merged, brand, rng)
    _dedupe_faq_duplicate_answers(merged, rng)
    _expand_blog_post_bodies(
        merged,
        name,
        str(brand.get("city") or ""),
        str(brand.get("country") or ""),
        activity,
        rng,
        vid_key,
        brand=brand,
    )
    if vid_key == "cafe_restaurant":
        hparts = [
            str(brand.get("hours_weekday") or "").strip(),
            str(brand.get("hours_weekend") or "").strip(),
        ]
        merged["hours_display"] = " · ".join(p for p in hparts if p)
    return merged


def _dedupe_faq_duplicate_answers(merged: dict[str, Any], rng: random.Random) -> None:
    """Avoid identical FAQ answer bodies (common generator tell when pools overlap)."""
    faqs = merged.get("faq_items")
    if not isinstance(faqs, list):
        return
    seen: set[str] = set()
    extras = [
        "Ask us for a written note if you need specifics for your site.",
        "We confirm details on a short call before scheduling.",
        "Exact timing depends on access and season.",
    ]
    for it in faqs:
        if not isinstance(it, dict):
            continue
        raw = str(it.get("a") or "")
        plain = re.sub(r"<[^>]+>", " ", raw)
        key = " ".join(plain.split()).strip().lower()[:220]
        if len(key) < 28:
            continue
        if key in seen:
            it["a"] = raw + "<p>" + rng.choice(extras) + "</p>"
        else:
            seen.add(key)


def build_service_area_page_html(
    zone: str,
    *,
    brand_name: str,
    activity: str,
    founded_year: int | str,
    page_ext: str,
    service_items: list[Any],
    vertical_id: str,
    rng: random.Random,
    city: str = "",
    brand: dict[str, Any] | None = None,
) -> str:
    """Several structural templates so service-area pages are not thin duplicates."""
    z = (zone or "").strip()
    act = (activity or "services").strip()
    vid = (vertical_id or "").strip()
    fy = str(founded_year or "").strip() or "2015"
    z_e, bn_e, act_e, fy_e = escape(z), escape(brand_name), escape(act), escape(fy)
    head_line = escape(act.strip().title())
    ext = escape(page_ext)

    svc_list_html = ""
    if isinstance(service_items, list) and service_items:
        items_html = "".join(
            f"<li><strong>{escape(str(s.get('title', '')))}</strong>: {escape(str(s.get('text', '')))}</li>"
            for s in service_items
            if isinstance(s, dict)
        )
        svc_list_html = f"<ul>{items_html}</ul>"

    if vid in ("dental", "medical"):
        lead = (
            f"<p>{bn_e} sees patients from {z_e} and nearby neighborhoods, with scheduling that respects "
            f"workday constraints and follow-up clarity after each visit.</p>"
        )
    elif vid in _TRADES_VERTICALS:
        lead = (
            f"<p>Crews covering {z_e} know local access rules, parking limits, and how to stage work without "
            f"surprising residents or building managers — we’ve run {act_e} jobs here since {fy_e}.</p>"
        )
    elif vid in ("legal", "accounting"):
        lead = (
            f"<p>Clients in {z_e} get the same document discipline as downtown matters: clear scopes, "
            f"written timelines, and no surprise line items after engagement letters are signed.</p>"
        )
    else:
        lead = (
            f"<p>{bn_e} provides professional {act_e} throughout {z_e} and surrounding areas. "
            f"Our team has been active here since {fy_e}, with scheduling that fits how your organization actually runs.</p>"
        )

    b_sa = brand if isinstance(brand, dict) else {}
    lead_block = lead
    if vid in _TRADES_VERTICALS and rng.random() < 0.68:
        lead_block += (
            f"<p>{season_phrase(b_sa, rng).capitalize()} still reshuffles routing around {z_e}; "
            f"dispatch texts if the second stop slides, not after you’ve already waited.</p>"
        )
    if rng.random() < 0.52:
        lead_block += (
            f"<p>Narrow streets and curb rules near {z_e} eat setup time — arrival windows account for that.</p>"
        )
    city_t = (city or "").strip()
    if city_t and rng.random() < 0.38:
        c_e = escape(city_t)
        lead_block += (
            f"<p>We still coordinate {act_e} from {c_e} into {z_e} regularly — same contact tree, "
            f"just different parking math.</p>"
        )

    mid_tail_a = rng.choice(
        [
            "<p>Written estimates before we mobilize; arrival windows confirmed by dispatch; photos or checklists on request.</p>",
            "<p>Estimates hit your inbox before mobilization; dispatch confirms windows; photo checklists stay optional but common.</p>",
        ],
    )
    mid_tail_b = rng.choice(
        [
            (
                f"<p>We confirm building rules, after-hours access, and contact trees before the first visit — "
                f"especially for multi-tenant addresses in {z_e}.</p>"
            ),
            (
                f"<p>Multi-tenant addresses in {z_e} mean we lock escorts, badges, and after-hours rules before day one — "
                f"no improvised lobby negotiations.</p>"
            ),
        ],
    )
    mid_a = (
        f"<h2>Services we deliver in {z_e}</h2>{svc_list_html}"
        f"<h2>How we work on-site in {z_e}</h2>"
        f"{mid_tail_a}"
    )
    mid_b = (
        f"<h2>Typical requests in {z_e}</h2>{svc_list_html}"
        f"<h2>Scheduling and access</h2>"
        f"{mid_tail_b}"
    )
    mid_c = (
        f"<h2>Quick facts for {z_e} clients</h2>"
        f"<ul>"
        f"<li>Supervisor-named on your file for repeat work</li>"
        f"<li>Change orders only after written approval</li>"
        f"<li>Emergency line monitored when advertised on our contact page</li>"
        f"</ul>"
        f"<h2>Core offerings</h2>{svc_list_html}"
    )
    cta = f"<p><a href='contact.{ext}' class='btn'>Get a quote for {z_e}</a></p>"

    why_local = rng.choice(
        [
            "<p>Local familiarity means fewer reschedules, realistic arrival windows, and crews who treat neighborhood reputation as part of the job.</p>",
            "<p>Fewer surprise reschedules, windows that match curb reality, and crews who assume neighbors talk to each other.</p>",
        ],
    )
    layouts = [
        f"<section class='block'><div class='container narrow'><h1>{head_line} in {z_e}</h1>{lead_block}{mid_a}{cta}</div></section>",
        f"<section class='block'><div class='container narrow'><h1>{head_line} — {z_e}</h1>{lead_block}{mid_b}{cta}</div></section>",
        f"<section class='block'><div class='container narrow'><h1>{bn_e} in {z_e}</h1>{lead_block}{mid_c}{cta}</div></section>",
        f"<section class='block'><div class='container narrow'><h1>{head_line} serving {z_e}</h1>"
        f"{mid_b}{lead_block}<h2>What we offer</h2>{svc_list_html}{cta}</div></section>",
        f"<section class='block'><div class='container narrow'><h1>{z_e}: {head_line}</h1>{lead_block}"
        f"<h2>Why {z_e} teams choose {bn_e}</h2>"
        f"{why_local}"
        f"<h2>Services</h2>{svc_list_html}{cta}</div></section>",
    ]
    return layouts[rng.randrange(len(layouts))]


def _inject_service_pricing(
    service_items: list[Any],
    vertical_id: str,
    rng: random.Random,
    brand: dict[str, Any],
) -> None:
    vid = vertical_id.strip()
    ctry = str(brand.get("country") or "").strip()
    if vid == "news":
        for it in service_items:
            if isinstance(it, dict) and "price_from" in it:
                it.pop("price_from", None)
        return
    pools: dict[str, list[str]] = {
        "cafe_restaurant": ["From $16", "Chef’s table $78", "Wine pairings +$42"],
        "cleaning": ["Office routes from $165", "Deep clean from $340", "Move-out from $290"],
        "fitness": ["Membership from $64/mo", "Drop-in $27", "PT block $720 (10×45m)"],
        "clothing": ["Tees from $36", "Outerwear from $148", "Bundles from $112"],
        "news": ["Team briefings from $240/mo", "API access from $490/mo"],
        "marketing_agency": ["Technical audits from $2.6k", "Retainers from $5.2k/mo", "Sprints from $9.8k"],
        "dental": ["Hygiene visit from $120", "Whitening from $450", "Crown consult from $195"],
        "plumbing": ["Drain service from $125", "Water heater tune-up from $285", "After-hours visit from $195"],
        "roofing": ["Inspection from $350", "Repairs from $650", "Replacement quotes from $8.5k"],
        "landscaping": ["Weekly maintenance from $180", "Seasonal cleanup from $420", "Design consult from $275"],
        "consulting": ["Strategy workshop from $3.8k", "Advisory day from $1.9k", "Quarterly program from $6.2k"],
        "moving": ["Local move from $480", "Two-bedroom pack from $920", "Long-distance estimate from $2.4k"],
        "hvac": ["Tune-up from $129", "Diagnostic from $95", "Duct cleaning from $420"],
        "legal": ["Initial consult from $350", "Contract review from $780", "Filing package from $1.2k"],
        "medical": ["New patient visit from $185", "Follow-up from $95", "Lab panel from $140"],
        "electrical": ["Service call from $125", "Panel work from $850", "EV charger install from $1.8k"],
        "auto_repair": ["Oil service from $72", "Brake job from $320", "Diagnostics from $125"],
        "real_estate": ["Buyer consult complimentary", "Listing prep from $495", "Staging consult from $350"],
        "accounting": ["Personal return from $220", "Bookkeeping from $285/mo", "Corporate year-end from $1.8k"],
        "pest_control": ["Interior treatment from $165", "Perimeter plan from $95/mo", "Inspection from $125"],
    }
    agency_fallback = ["Project tiers from $3.2k", "Day blocks from $1.35k", "Retainers from $4.8k/mo"]
    neutral_local = ["Service visit from $125", "Standard scope from $285", "Priority booking from $195"]
    if vid in pools:
        opts = list(pools[vid])
    elif vid == "generic":
        opts = list(agency_fallback)
    else:
        opts = list(neutral_local)
    rng.shuffle(opts)
    for i, it in enumerate(service_items):
        if not isinstance(it, dict):
            continue
        if (it.get("price_from") or "").strip():
            continue
        it["price_from"] = localize_money_labels(opts[i % len(opts)], ctry)


def _blog_vocab(vertical_id: str) -> dict[str, str]:
    vid = vertical_id.strip()
    pools: dict[str, dict[str, str]] = {
        "cafe_restaurant": {
            "where": "the line and the dining room",
            "unit": "covers",
            "focus": "tickets, allergens, and pacing",
        },
        "cleaning": {
            "where": "your building’s high-traffic zones",
            "unit": "routes and walkthroughs",
            "focus": "chemistry choices, timing, and proof for auditors",
        },
        "fitness": {
            "where": "the floor during peak blocks",
            "unit": "classes and open gym",
            "focus": "safety, capacity, and coaching consistency",
        },
        "clothing": {
            "where": "fit rooms and fulfillment",
            "unit": "drops and returns",
            "focus": "fabric notes, sizing honesty, and carrier cutoffs",
        },
        "news": {
            "where": "the desk before publish",
            "unit": "stories and briefings",
            "focus": "verification, corrections, and source protection",
        },
        "marketing_agency": {
            "where": "client analytics and staging",
            "unit": "audits and releases",
            "focus": "measurable changes, not slide decks",
        },
        "dental": {
            "where": "the chair and sterilization path",
            "unit": "appointments and treatment blocks",
            "focus": "consent, imaging, and follow-up clarity",
        },
        "medical": {
            "where": "exam rooms and intake",
            "unit": "visits and referrals",
            "focus": "documentation, continuity, and patient communication",
        },
        "plumbing": {
            "where": "the service van and mechanical rooms",
            "unit": "calls and callbacks",
            "focus": "access, parts on hand, and written scope before work starts",
        },
        "roofing": {
            "where": "the roofline and ground perimeter",
            "unit": "inspections and crew days",
            "focus": "weather windows, safety, and photo documentation",
        },
        "landscaping": {
            "where": "beds, turf, and hardscape transitions",
            "unit": "routes and seasonal passes",
            "focus": "irrigation, plant health, and realistic maintenance windows",
        },
        "consulting": {
            "where": "workshops and leadership calendars",
            "unit": "sprints and steering sessions",
            "focus": "decisions, owners, and written next steps",
        },
        "moving": {
            "where": "loading docks and residence access",
            "unit": "truck days and packing crews",
            "focus": "inventory labels, building rules, and damage protocols",
        },
        "hvac": {
            "where": "mechanical rooms and occupied spaces",
            "unit": "service calls and seasonal tune-ups",
            "focus": "refrigerant handling, filtration, and comfort targets",
        },
        "legal": {
            "where": "the file and the docket",
            "unit": "drafts and filings",
            "focus": "deadlines, evidence, and client instructions in writing",
        },
        "electrical": {
            "where": "panels, conduit, and finished spaces",
            "unit": "service calls and installs",
            "focus": "permits, arc safety, and power budgets",
        },
        "auto_repair": {
            "where": "the bay and the lift",
            "unit": "ROs and inspections",
            "focus": "parts lead times, warranty notes, and test drives",
        },
        "real_estate": {
            "where": "showings and closing desks",
            "unit": "listings and offers",
            "focus": "disclosures, comparables, and timeline discipline",
        },
        "accounting": {
            "where": "close calendars and client inboxes",
            "unit": "files and filings",
            "focus": "source documents, reconciliations, and CRA-ready packages",
        },
        "pest_control": {
            "where": "perimeter and interior access points",
            "unit": "treatments and follow-ups",
            "focus": "product choice, pet safety, and written re-entry times",
        },
        "generic": {
            "where": "day-to-day operations on site",
            "unit": "visits and scheduled work",
            "focus": "clear scope, one accountable lead, and realistic dates",
        },
    }
    return pools.get(vid) or pools["generic"]


def _expand_blog_post_bodies(
    merged: dict[str, Any],
    brand_name: str,
    city: str,
    country: str,
    activity: str,
    rng: random.Random,
    vertical_id: str,
    brand: dict[str, Any] | None = None,
) -> None:
    posts = merged.get("blog_posts")
    if not isinstance(posts, list):
        return
    loc = city or "our market"
    ctry = (country or "").strip()
    locale_hint = f"{loc}, {ctry}" if ctry else loc
    voc = _blog_vocab(vertical_id)
    n_styles = 8
    b_payload = brand if isinstance(brand, dict) else {}
    for i, p in enumerate(posts):
        if not isinstance(p, dict) or p.get("body_paragraphs") or p.get("article_sections_html"):
            continue
        title = str(p.get("title") or "Update")
        excerpt = str(p.get("excerpt") or "")
        tlow = title.lower()
        ex_block = excerpt.strip() or (
            f"We published this because the same questions about {tlow} kept arriving from {loc} — "
            f"a single page beats repeating it on every call."
        )
        style = (i * 3 + rng.randrange(0, n_styles)) % n_styles
        first_alts: list[str]
        if style == 0:
            first_alts = [
                f"We drafted this after another week of {voc['where']} in {loc}. The question behind “{tlow}” keeps showing up, so here’s how {brand_name} actually handles it — not the brochure version.",
                f"Another week of {voc['where']} in {loc}, and “{tlow}” is still the phrase people lead with — here’s the non-brochure version from {brand_name}.",
                f"If you’re comparing notes on {tlow} in {loc}, this is the workflow we actually run — not a slide-deck fantasy.",
            ]
            paras = [
                rng.choice(first_alts),
                f"{ex_block} In practice that means {voc['focus']}; anything cute on paper that the team can’t repeat gets cut.",
                f"If you’re comparing vendors for {activity}, skim for specifics: who owns what, what “done” looks like, and how disagreements get resolved. Fancy adjectives cost nothing.",
                "When we change a procedure, we’ll say so here. No silent rewrites.",
            ]
        elif style == 1:
            second = (
                f"{excerpt.strip()} — here’s the longer view for anyone planning work with {brand_name} soon."
                if excerpt.strip()
                else f"This note is for anyone planning work with {brand_name} in the next quarter."
            )
            first_alts = [
                f"Short answer: {tlow} shows up constantly for our audience in {loc}, so we published this instead of repeating the same talking points on every call. Long answer follows.",
                f"{tlow} keeps landing in our inbox from {loc}; we’d rather publish once than repeat the same call script.",
                f"Quick version: {tlow} is a recurring thread for neighbors in {loc} — the long version is below.",
            ]
            paras = [
                rng.choice(first_alts),
                second,
                f"Our {voc['unit']} depend on steady habits — {voc['focus']}. That’s the lens for everything below.",
                f"None of this replaces a written scope for {activity}; it’s background so you’re not guessing.",
            ]
        elif style == 2:
            first_alts = [
                f"Field note from {brand_name}: people read “{tlow}” and picture different outcomes. Here’s the version we stand behind in {loc}.",
                f"Same headline, three different mental pictures — here’s what {tlow} means on our crew in {loc}.",
                f"On the ground in {loc}, {tlow} is less abstract than it reads online; this is our working definition.",
            ]
            paras = [
                rng.choice(first_alts),
                f"{ex_block} We’d rather be a little plain-spoken than promise a workflow we don’t run weekly.",
                f"Side by side with the rest of what we publish on {activity}, this should read like one thread — not a one-off sales patch.",
                "Typos fixed quietly; policy or pricing shifts get called out.",
            ]
        elif style == 3:
            first_alts = [
                f"Internally we file this under {tlow}. Externally it’s just honest detail for neighbors in {loc} who like to read before they call.",
                f"Neighborhood readers in {loc} asked for plain detail on {tlow}; this is the file we’d send a friend.",
                f"Call it {tlow} or call it housekeeping — either way, here’s what we tell people in {loc} before they book.",
            ]
            paras = [
                rng.choice(first_alts),
                ex_block,
                f"The through-line is {voc['focus']}. If that bores you, we’re probably a good fit — we optimize for repeatability, not hype.",
                f"Seasonal volume and carrier cutoffs around {locale_hint} can move dates; the contact page stays the source for hours and blackouts.",
            ]
        elif style == 4:
            first_alts = [
                f"Why bother writing about {tlow}? Because {brand_name} gets the same three emails every month, and a public answer saves everyone time.",
                f"We’re not philosophizing about {tlow} — we’re answering the emails that repeat every month.",
                f"This post exists because {tlow} generates the same three questions; a page is cheaper than a voicemail loop.",
            ]
            paras = [
                rng.choice(first_alts),
                ex_block,
                f"Behind the scenes in {loc}, {voc['where']} is where theory meets {voc['unit']}. That’s what we’re describing.",
                f"Competing quotes for {activity}? Ask how they document {voc['focus']} — not just what they promise in the subject line.",
            ]
        elif style == 5:
            first_alts = [
                f"A few paragraphs on {tlow} won’t replace a conversation, but it should remove the obvious unknowns for people near {loc}.",
                f"You don’t need a manifesto on {tlow} — you need the unknowns removed if you’re near {loc}.",
                f"Think of this as a pre-call brief on {tlow} for anyone around {loc}.",
            ]
            paras = [
                rng.choice(first_alts),
                f"{ex_block} We keep {voc['unit']} tight so surprises are rare and fixable.",
                f"Everything here aligns with how we talk about {activity} on services and FAQ — if you spot a clash, the newer dated note wins.",
                "Thanks for reading; the team sees patterns in these posts and adjusts training when the same confusion pops up twice.",
            ]
        elif style == 6:
            first_alts = [
                f"Not everyone needs a deep dive on {tlow}. If you’re skimming: we care about {voc['focus']}, and we’re based in {loc}.",
                f"Skimming? {tlow} boils down to {voc['focus']} for us — and we’re in {loc} when you want the longer version.",
                f"If {tlow} isn’t your whole week, start here: {voc['focus']}, {loc}, {brand_name}.",
            ]
            paras = [
                rng.choice(first_alts),
                ex_block,
                f"For {activity}, we’ve learned that {voc['where']} exposes gaps faster than any strategy workshop. This article is mostly lessons from that.",
                f"Reach out through the site if your situation is unusual — templates help most people, not every edge case.",
            ]
        else:
            first_alts = [
                f"This month’s note on {tlow} — written for clients and regulars around {loc}, not for a generic checklist.",
                f"Regulars around {loc} asked for a dated note on {tlow}; this is it — not a generic checklist.",
                f"Seasonal update on {tlow} for people who already know {brand_name} in {loc}.",
            ]
            paras = [
                rng.choice(first_alts),
                ex_block
                if excerpt.strip()
                else f"{brand_name} tries to publish concrete detail; fluff makes audits and handoffs harder.",
                f"We tie {voc['unit']} back to {voc['focus']} so {activity} doesn’t drift into “we’ll figure it out later.”",
                "Updated when reality changes; the date in the byline is the anchor.",
            ]
        if prose_humanize_enabled(b_payload, merged):
            register = pick_register(rng)
            micro = prose_micro_imperfections_enabled(b_payload, merged)
            paras[0] = rewrite_if_stale_opener(paras[0], first_alts, rng)
            if rng.random() < 0.48:
                short_ledes = [
                    f"{tlow.title()} shows up weekly in {loc}.",
                    f"Same question, new week: {tlow}.",
                    f"Quick context on {tlow} for {loc}.",
                ]
                paras[0] = rng.choice(short_ledes)
            elif register == "conversational" and rng.random() < 0.26:
                paras[0] = apply_conversational_leadin(paras[0], rng)
            if micro:
                paras[0] = apply_micro_imperfections(paras[0], rng)
            paras = dedupe_paragraph_openers(paras, rng)
            inj = rng.randrange(len(paras))
            paras[inj] = inject_local_detail(paras[inj], b_payload, rng)
            paras = vary_paragraph_shape(paras, rng)
        if rng.random() < 0.45:
            paras[0], paras[1] = paras[1], paras[0]
        p["body_paragraphs"] = paras


def _hero_cta_for_vertical(vertical_id: str, rng: random.Random) -> tuple[str, str]:
    vid = vertical_id.strip()
    pools: dict[str, list[str]] = {
        "cafe_restaurant": ["Reserve a table", "Book now", "Contact us"],
        "cleaning": ["Get a quote", "Schedule a walkthrough", "Contact us"],
        "fitness": ["Book a tour", "Start a trial", "Contact us"],
        "clothing": ["Shop the drop", "Sizing help", "Contact support"],
        "news": ["Tip the newsroom", "Send documents securely", "Contact the desk"],
        "marketing_agency": ["Book a discovery call", "Request an audit", "Contact us"],
        "dental": ["Book appointment", "Schedule a visit", "Contact us"],
        "plumbing": ["Get a quote", "Schedule service", "Call now"],
        "roofing": ["Free inspection", "Get an estimate", "Contact us"],
        "landscaping": ["Request site visit", "Get a quote", "Contact us"],
        "consulting": ["Book a call", "Request proposal", "Contact us"],
        "moving": ["Get a quote", "Schedule your move", "Contact us"],
        "hvac": [
            "Schedule service",
            "Book inspection",
            "Free estimate",
            "Request service",
            "Schedule maintenance",
            "Emergency service",
            "Contact us",
        ],
        "legal": ["Free consultation", "Schedule a call", "Contact us"],
        "medical": ["Book an appointment", "Schedule a visit", "Contact us"],
        "electrical": ["Request estimate", "Schedule service", "Contact us"],
        "auto_repair": ["Book service", "Get a quote", "Contact us"],
        "real_estate": ["Free consultation", "Contact an agent", "Get in touch"],
        "accounting": ["Free consultation", "Book a call", "Contact us"],
        "pest_control": ["Schedule inspection", "Get a quote", "Contact us"],
    }
    opts = pools.get(vid) or ["Contact us", "Book a consultation", "Get in touch"]
    return rng.choice(opts), "contact.php"


_HERO_FALLBACK_GENERIC: tuple[str, ...] = (
    "Clear scope, named owners, and dates you can plan around — without the usual runaround.",
    "We document assumptions up front so delivery does not depend on hallway agreements.",
    "If timelines slip, you hear from the person who owns the task — not a generic inbox.",
)

_HERO_FALLBACK_BY_VERTICAL: dict[str, tuple[str, ...]] = {
    "pest_control": (
        "Licensed inspections, species-specific treatments, and prevention plans that close entry points — not just spray-and-go.",
        "Targeted interior and exterior programs with written re-entry timing and product notes you can file.",
        "Integrated pest management: identify first, treat where it matters, then monitor so problems do not bounce back.",
    ),
    "cleaning": (
        "Route-based crews, written scopes, and checklists your facility manager can audit without shadowing every visit.",
        "We standardize chemistry and touch-points so quality stays predictable when staff or buildings change.",
    ),
}


def _ensure_hero_distinct_from_about(merged: dict[str, Any], rng: random.Random) -> None:
    hero = str(merged.get("hero_subtitle") or "").strip()
    about = str(merged.get("about_body") or "").strip()
    if len(hero) < 28 or len(about) < 45:
        return
    h_norm = " ".join(hero.split()).lower()[:240]
    a_norm = " ".join(about.split()).lower()
    if h_norm and h_norm in a_norm:
        vid = str(merged.get("vertical_id") or "").strip()
        pool = _HERO_FALLBACK_BY_VERTICAL.get(vid) or _HERO_FALLBACK_GENERIC
        merged["hero_subtitle"] = rng.choice(pool)
        return
    hw = set(re.sub(r"[^a-z0-9]+", " ", h_norm).split())
    aw = set(re.sub(r"[^a-z0-9]+", " ", a_norm[:480]).split())
    if len(hw) >= 12 and len(aw) >= 12:
        inter = len(hw & aw)
        if inter / max(1, len(hw)) >= 0.52:
            vid = str(merged.get("vertical_id") or "").strip()
            pool = _HERO_FALLBACK_BY_VERTICAL.get(vid) or _HERO_FALLBACK_GENERIC
            merged["hero_subtitle"] = rng.choice(pool)


def _dedupe_similar_sentences(body: str, *, sim: float = 0.82) -> str:
    """Drop consecutive-style duplicate thoughts (high word overlap) from about/lead text."""
    s = (body or "").strip()
    if len(s) < 50:
        return s
    parts = re.split(r"(?<=[.!?])\s+", s)
    out: list[str] = []
    for pt in parts:
        p = pt.strip()
        if not p:
            continue
        w = set(re.sub(r"[^a-z0-9]+", " ", p.lower()).split())
        if len(w) < 6:
            out.append(p)
            continue
        drop = False
        for prev in out:
            pw = set(re.sub(r"[^a-z0-9]+", " ", prev.lower()).split())
            if len(pw) < 6:
                continue
            inter = len(w & pw)
            ratio = inter / max(1, min(len(w), len(pw)))
            if ratio >= sim:
                drop = True
                break
        if not drop:
            out.append(p)
    return " ".join(out).strip()


def _prepend_local_story(merged: dict[str, Any], brand: dict[str, Any], name: str, rng: random.Random) -> None:
    city = str(brand.get("city") or "").strip()
    fy = brand.get("founded_year")
    region = str(brand.get("region") or "").strip()
    reg = f", {region}" if region else ""
    body = (merged.get("about_body") or "").strip()
    if not body or not city or not fy:
        return
    fy_i = int(fy) if str(fy).strip().isdigit() else None
    if fy_i is None:
        return
    cy = as_of_year(brand)
    tenure = max(0, cy - fy_i)
    if tenure >= 2:
        tenure_phrase = f"for {tenure} years"
    elif tenure == 1:
        tenure_phrase = "for over a year"
    else:
        tenure_phrase = "since launch"
    leads = [
        f"Founded in {fy}, {name} has been part of the {city} community {tenure_phrase}. ",
        f"Since {fy}, {name} has run day-to-day operations from {city}{reg}. ",
        f"{name} took root in {city} in {fy}; the neighborhood still shapes how we hire and train. ",
        f"Our {city} base{reg} dates to {fy} — long enough to see what repeats every season and what doesn’t. ",
        f"What started in {fy} as a small {city} crew is now the same group answering the phone and the inbox. ",
    ]
    vid_loc = str(merged.get("vertical_id") or "").strip()
    trades_scene = vid_loc in _TRADES_VERTICALS or vid_loc in ("cleaning", "pest_control")
    if trades_scene:
        scene_leads = [
            f"The phone still rings early on Mondays in {city} — dispatch still runs off written scopes, not memory. ",
            f"In {city}, {name} still rolls trucks with checklists tied to the address — not a one-line text and a guess. ",
            f"Seasons shift pest pressure in {city}; {name} adjusts perimeter work instead of repeating last month’s map. ",
            f"First call of the day in {city} is usually routing and timing — {name} answers it like operations, not sales theatre. ",
        ]
    else:
        scene_leads = [
            f"The phone still rings early on Mondays in {city} — same habit {name} built its roster around. ",
            f"Walk past {name} on a Thursday in {city} and you’ll still see checklists, not improvisation, behind the counter. ",
            f"In {city}, the first message of the day is rarely glamorous; {name} answers it anyway — that’s the job. ",
            f"Seasons change in {city}; the through-line at {name} is the same crew learning what repeats and what doesn’t. ",
        ]
    lead = rng.choice(scene_leads if rng.random() < 0.44 else leads)
    if lead.rstrip() in body:
        return
    merged["about_body"] = lead + body


_ABOUT_EXTRA_POOLS: dict[str, list[str]] = {
    "cafe_restaurant": [
        "We adjust prep when producers peak, and the team rehearses allergens and pacing so large parties never feel forgotten.",
        "On busy nights you’ll see the same leads — able to smooth a late seating and remember guests who come back.",
        "Wine and non-alc lists get trimmed together so pairings stay honest when the room is full.",
        "The pastry window doubles as a prep checkpoint: if it looks tired, it doesn’t hit the pass.",
        "Local suppliers get a standing quarterly review — not because we love meetings, because menus drift otherwise.",
    ],
    "pest_control": [
        "Technicians photo-map harborage before treatment so the next visit targets the same gaps, not a fresh guess.",
        "Product choices follow label directions and your sector’s rules — kitchens, schools, and clinics get different defaults.",
        "Exclusion notes go to maintenance with dates so small gaps do not reopen between quarterly visits.",
        "Emergency calls get a capped response window and a written plan before we apply anything indoors.",
        "Seasonal pressure (ants in spring, rodents in fall) is built into the calendar — not a surprise upsell mid-year.",
    ],
    "cleaning": [
        "Crew leads work from checklists matched to your building class, with SDS binders and insurance paperwork ready for audits.",
        "When you remodel or change hours, we redraw routes instead of stretching an old plan across new traffic patterns.",
        "We photograph high-touch zones on request so facility teams can compare week-over-week without walking every floor.",
        "Holiday blackouts are published a month out; no surprise ‘we forgot your building’ texts.",
        "Chemistry switches (stone vs. epoxy vs. carpet) are documented on the work order, not left to memory.",
    ],
    "marketing_agency": [
        "We keep a running changelog of shipped work so you can tie rankings and conversions back to specific releases.",
        "Discovery workshops stay small — enough stakeholders to decide, not so many that every round needs a fresh deck.",
        "Staging environments stay tagged; you always know what’s live vs. what’s queued.",
        "We’d rather decline a channel than run one half-resourced and blame the algorithm later.",
        "Reporting defaults to numbers your CFO recognizes, not vanity dashboards.",
    ],
    "fitness": [
        "Floor staff enforce equipment etiquette and spot heavy work; we pause a set rather than guessing on depth.",
        "Trial visits include a short movement screen so coaches can point you toward classes or open gym honestly.",
        "Class caps exist so coaching quality doesn’t collapse when a post goes viral.",
        "We log equipment service the same way we log memberships — boring, until it prevents an injury.",
        "Music volume follows a simple rule: can the coach’s voice cut through without shouting?",
    ],
    "news": [
        "Corrections sit at the top of a story with a timestamp; bullets that age out get rewritten or marked superseded.",
        "Tip lines are read by editors who know legal and safety limits before anyone runs with a hot lead.",
        "Syndication partners get the same contract clauses — we don’t negotiate integrity per outlet.",
        "Data graphics ship with source links; if the CSV moves, the chart gets pulled or updated same day.",
        "Weekend desks are staffed thin on purpose; we’d rather be slow than sloppy.",
    ],
    "clothing": [
        "We photograph flat lays and on-body shots against the same stock so you can trust measurements against drape.",
        "If a fabric changes between drops, we say so in the copy instead of hoping nobody notices after wash.",
        "Return windows stay visible on the product page, not buried in PDF terms.",
        "Sale-week shipping cutoffs post in local time — we’d rather lose a cart than lie about carrier scans.",
        "Lookbook shots use the same steam-and-hang protocol as warehouse QA so expectations match delivery.",
    ],
    "legal": [
        "Conflict checks run before we open a file — no exceptions, even when timelines are tight.",
        "Retainers spell out assumptions, exclusions, and who owns each workstream so invoices never surprise.",
        "We keep privilege and joint-client issues explicit in writing when more than one party is in the room.",
        "Successor counsel should be able to pick up the file without reverse-engineering half-finished drafts.",
        "Regulatory references in client memos carry a date stamp; we refresh when rules or guidance moves.",
        "Document preservation starts at intake — spoliation is harder to fix than to prevent.",
        "Settlement discussions are labeled so without-prejudice protections actually apply when they need to.",
        "In-house and external teams share one fact index; divergent binders are where expensive drift starts.",
        "Risk calls are short, dated, and filed — not buried in long email chains nobody can find later.",
        "Cross-border angles get local counsel named early; this office does not pretend one bar covers every jurisdiction.",
    ],
    "accounting": [
        "Month-end close packs use the same chart and mapping every cycle — ad hoc spreadsheets do not replace the GL.",
        "CRA correspondence is threaded by issue with dates; responses stay coherent when multiple agents touch a file.",
        "T-slips and contractor characterization are reconciled before year-end; January surprises are optional.",
        "GST and HST positions are documented before filing; we do not rely on bank-feed maps as source of truth.",
        "Related-party pricing and terms are on paper before the year closes — reconstructed memos rarely survive review.",
        "Payroll remittances and corporate instalments sit on separate calendars; missing one does not excuse the other.",
        "Restricted funds and charity rules get their own checklist when a file is non-profit or hybrid.",
        "Software exports help, but judgment still lands with the engagement team and the working papers.",
        "Year-end accruals are supported by invoices or third-party confirms — not back-of-envelope estimates.",
        "We flag when books are behind; catch-up work gets scoped before we promise filing dates.",
    ],
    "consulting": [
        "Discovery stays small enough to decide — not so large that every round needs a fresh deck.",
        "Statements of work name deliverables, owners, and review gates before kickoff accelerates.",
        "Steering readouts are one page: decisions made, risks open, and what we need from you next week.",
        "We document assumptions when data is incomplete; scope changes get written, not implied.",
        "Vendor and internal handoffs use a single decision log so teams do not contradict each other in parallel.",
        "Quality gates are explicit — we do not ship milestones that fail the checks we agreed upfront.",
        "Post-engagement notes capture what worked and what to watch; repeat clients should not relitigate the basics.",
        "Risk registers stay visible through delivery — hiding issues until the final week is not how we operate.",
        "Workstreams have named leads on both sides; ‘the committee’ is not an accountable owner.",
        "When we decline a workstream, we say so early — half-resourced lanes create more damage than saying no.",
    ],
}

_ABOUT_SHORT_SNIPPETS: dict[str, list[str]] = {
    "cafe_restaurant": [
        "Busy nights need the same leads every week.",
        "Menus drift without disciplined supplier reviews.",
        "Allergen notes live on tickets, not memory.",
        "The pass stays quiet when prep is honest.",
    ],
    "pest_control": [
        "Harborages get photo-mapped before treatment.",
        "Re-entry times follow label and sector rules.",
        "Exclusion notes go straight to maintenance.",
        "Emergency calls get a written plan first.",
    ],
    "cleaning": [
        "Routes redraw when your hours change.",
        "SDS binders belong beside supplies, not in a drawer.",
        "Photos beat arguments on quality.",
        "Holiday blackouts publish early.",
    ],
    "marketing_agency": [
        "Changelog ties releases to outcomes.",
        "Staging tags separate live from queued.",
        "We decline channels we can’t run whole.",
        "Reports speak CFO, not vanity.",
    ],
    "fitness": [
        "Class caps protect coaching quality.",
        "Trials include a real screen, not a sales ambush.",
        "Equipment logs are boring until they prevent injury.",
        "Coaches should not shout over the playlist.",
    ],
    "news": [
        "Corrections live at the top with a time stamp.",
        "Thin weekend desks beat sloppy speed.",
        "Graphics ship with sources or not at all.",
        "Syndication rules don’t bend per partner.",
    ],
    "clothing": [
        "Fabric changes get named in copy.",
        "Return windows stay visible, not buried.",
        "Flat and on-body shots use the same rig.",
        "Cutoffs post in local time.",
    ],
    "legal": [
        "Conflict checks precede every file.",
        "Retainers name exclusions plainly.",
        "Risk notes are short, dated, filed.",
        "Cross-border gets local counsel early.",
    ],
    "accounting": [
        "GL mapping stays consistent month to month.",
        "CRA threads stay one issue per chain.",
        "GST positions get documented before filing.",
        "Catch-up work gets scoped before dates are promised.",
    ],
    "consulting": [
        "SOWs name review gates upfront.",
        "Assumptions get written when data lags.",
        "Declining half-resourced work is a feature.",
        "Decision logs beat parallel email threads.",
    ],
}

_GENERIC_ABOUT_SHORT: tuple[str, ...] = (
    "One accountable lead owns the thread end to end.",
    "Written handoffs survive turnover better than hallway deals.",
    "Scope changes get a short addendum before more work ships.",
    "We rehearse edge cases when the downside of a miss is high.",
    "Checklists scale; heroics don’t.",
    "Clients hear from a named owner when dates slip.",
)


def _about_short_snippet_pool(vertical_id: str, brand: dict[str, Any]) -> list[str]:
    vid = (vertical_id or "").strip()
    if vid in _ABOUT_SHORT_SNIPPETS:
        return list(_ABOUT_SHORT_SNIPPETS[vid])
    sk = site_key_from_brand(brand)
    b = int(hashlib.sha256(f"about_s|{sk}|{vid}".encode("utf-8")).hexdigest(), 16) % len(_GENERIC_ABOUT_SHORT)
    return [_GENERIC_ABOUT_SHORT[(b + j) % len(_GENERIC_ABOUT_SHORT)] for j in range(3)]


_GENERIC_ABOUT_SPLITS: tuple[list[str], ...] = (
    [
        "Assumptions, owners, and dates are written down early so delivery doesn’t depend on hallway agreements.",
        "The people who scope work stay involved through launch — no surprise handoff to strangers at the finish line.",
        "We prefer one shared doc with version notes over six threads that contradict each other.",
    ],
    [
        "If a deadline slips, you hear from the owner of the task — not a generic inbox.",
        "Post-mortems are short: what broke, what we changed, what we’re watching next time.",
        "Budget and scope changes get acknowledged in writing before more work piles on.",
    ],
    [
        "Onboarding for new stakeholders includes a single source of truth — not a scavenger hunt through inboxes.",
        "We rehearse edge cases before go-live when the downside of a miss is high.",
        "Client access, approvals, and sign-off windows are named up front so timelines stay honest.",
    ],
)


def _about_extra_paragraph_pool(vertical_id: str, brand: dict[str, Any]) -> list[str]:
    vid = (vertical_id or "").strip()
    if vid in ("legal", "accounting", "consulting"):
        return list(_ABOUT_EXTRA_POOLS[vid])
    extra = _ABOUT_EXTRA_POOLS.get(vid)
    if extra is not None:
        return list(extra)
    sk = site_key_from_brand(brand)
    b = int(hashlib.sha256(f"about|{sk}|{vid}".encode("utf-8")).hexdigest(), 16) % len(_GENERIC_ABOUT_SPLITS)
    return list(_GENERIC_ABOUT_SPLITS[b])


def _append_about_paragraphs(
    merged: dict[str, Any],
    vertical_id: str,
    rng: random.Random,
    brand: dict[str, Any],
) -> None:
    long_pool = _about_extra_paragraph_pool(vertical_id, brand)
    short_pool = _about_short_snippet_pool(vertical_id, brand)
    body = (merged.get("about_body") or "").strip()
    if not body or not long_pool:
        return
    rng.shuffle(long_pool)
    rng.shuffle(short_pool)
    picks: list[str] = []
    if short_pool and len(long_pool) >= 1:
        s0, l0 = short_pool[0], long_pool[0]
        if rng.random() < 0.5:
            picks = [s0, l0]
        else:
            picks = [l0, s0]
    else:
        picks = long_pool[:2] if len(long_pool) >= 2 else long_pool[:1]
    for para in picks:
        p = para.strip()
        if p and p not in body:
            body = f"{body} {p}"
    merged["about_body"] = body


def _blog_post(title: str, excerpt: str, anchor: str, dt: tuple[str, str]) -> dict[str, Any]:
    display, iso = dt
    return {"title": title, "excerpt": excerpt, "date": display, "date_iso": iso, "anchor": anchor}


def _rebuild_blog_page_groups(merged: dict[str, Any], chunk: int = 3) -> None:
    posts = merged.get("blog_posts")
    if not isinstance(posts, list):
        merged["blog_page_groups"] = []
        return
    merged["blog_page_groups"] = [posts[i : i + chunk] for i in range(0, len(posts), chunk)]


def _ensure_blog_and_faq_pages(
    merged: dict[str, Any],
    name: str,
    activity: str,
    rng: random.Random,
    vertical_id: str,
    brand: dict[str, Any],
) -> None:
    merged.setdefault("faq_page_header", "Frequently asked questions")
    merged.setdefault("faq_page_sub", f"Clear answers about how {name} works with clients.")

    vid = vertical_id.strip()

    if vid == "news":
        merged.setdefault("blog_heading", "Latest coverage")
        merged.setdefault(
            "blog_intro",
            f"Reporting, explainers, and briefings from {name} — sourced and updated with care.",
        )
        merged.setdefault("blog_page_header", "Newsroom")
        merged.setdefault("blog_page_sub", "Stories, explainers, and editorial notes.")
        # Long-form posts + authors are attached in fill_content via enrich_news_vertical_content.
    elif vid == "cafe_restaurant":
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "From the kitchen & floor")
        merged.setdefault(
            "blog_intro",
            f"Notes on menus, service, and hospitality from {name}.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Seasonal menus, reservations, and guest experience.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post("What’s on the menu this month", "How we shorten the card when produce peaks and keep pacing smooth on Friday nights.", "monthly-menu", d5[0]),
                _blog_post("Reservations, walk-ins, and the bar", "How we hold tables without punishing guests who arrive on time.", "reservations", d5[1]),
                _blog_post("Suppliers we revisit every season", "Why a smaller producer list keeps the kitchen consistent.", "suppliers", d5[2]),
                _blog_post("Prep list: how we reduce waste before service", "Trim protocols and compost partners we rely on.", "prep-waste", d5[3]),
                _blog_post("Non-alcoholic pairings guests actually finish", "Shrubs, teas, and low-sugar builds that aren’t sweet overload.", "no-abv", d5[4]),
            ],
        )
    elif vid == "cleaning":
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "Facility notes")
        merged.setdefault(
            "blog_intro",
            f"Practical updates on schedules, sanitization, and upkeep from {name}.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Cleaning programs and quality checks.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post("How we plan routes around your hours", "Why staggered crews beat one big blitz in busy buildings.", "routes", d5[0]),
                _blog_post("High-touch surfaces after flu season", "What gets extra passes without alarming tenants.", "sanitization", d5[1]),
                _blog_post("Photo logs and spot audits", "When facility managers ask for evidence, we already have it.", "audits", d5[2]),
                _blog_post("Move-in / move-out sweeps", "Scope templates so landlords and tenants see the same checklist.", "move-clean", d5[3]),
                _blog_post("Green products: when we standardize vs. custom", "How we pick chemistry for stone, wood, and epoxy floors.", "green-chem", d5[4]),
            ],
        )
    elif vid == "fitness":
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "Training floor updates")
        merged.setdefault(
            "blog_intro",
            f"Programming notes, etiquette, and membership tips from {name}.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Coaching, classes, and open gym.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post("New block on the group schedule", "Why we cap attendance on strength days.", "schedule", d5[0]),
                _blog_post("Rack etiquette during peak hours", "Strip bars, share space, and keep transitions fast.", "etiquette", d5[1]),
                _blog_post("Trial visits: what to expect", "A short tour, a realistic warm-up, and no pressure on day one.", "trials", d5[2]),
                _blog_post("Deload weeks: why programmed light days matter", "How we keep PRs from stalling come month three.", "deload", d5[3]),
                _blog_post("Mobility that doesn’t eat the whole session", "Ten-minute warm-up blocks coaches actually use.", "mobility", d5[4]),
            ],
        )
    elif vid == "clothing":
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "Style & care notes")
        merged.setdefault(
            "blog_intro",
            f"Fit, fabric, and seasonal drops from {name}.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Sizing, drops, and product care.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post("How to read our measurement chart", "Flat measurements vs. on-body photos — what to trust for your build.", "measurements", d5[0]),
                _blog_post("This drop’s fabric callouts", "What changed from last season and how to wash it.", "fabrics", d5[1]),
                _blog_post("Returns without the runaround", "Clear steps if a piece doesn’t fit the way you hoped.", "returns", d5[2]),
                _blog_post("Capsule styling: three pieces, five outfits", "How we photograph pairings on the lookbook.", "capsule", d5[3]),
                _blog_post("Shipping cutoffs during sale weeks", "When labels actually scan before carriers close trucks.", "shipping", d5[4]),
            ],
        )
    elif vid == "marketing_agency":
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "Insights & updates")
        merged.setdefault(
            "blog_intro",
            f"Practical notes from {name} on {activity} — written for clients and partners.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Articles and updates from our team.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post(f"What {name} prioritizes this quarter", f"How we sequence technical work and content when tackling {activity}.", "priorities", d5[0]),
                _blog_post("Discovery: what we need in week one", "Access, analytics, and stakeholders — so audits don’t stall.", "discovery", d5[1]),
                _blog_post("Pre-launch checks for schema and CWV", "Validation, monitoring hooks, and rollback we agree on before go-live.", "prelaunch", d5[2]),
                _blog_post("Entity modeling without over-stuffing schema", "When extra types create noise for crawlers.", "entity-schema", d5[3]),
                _blog_post("Content briefs that writers actually use", "One-page outlines with intent, outline, and CTA.", "briefs", d5[4]),
            ],
        )
    else:
        d5 = past_dates_recent(rng, 5, brand=brand)
        merged.setdefault("blog_heading", "Insights & updates")
        merged.setdefault(
            "blog_intro",
            f"Practical notes from {name} on {activity} — written for clients and partners.",
        )
        merged.setdefault("blog_page_header", "Blog")
        merged.setdefault("blog_page_sub", "Articles and updates from our team.")
        merged.setdefault(
            "blog_posts",
            [
                _blog_post(f"What {name} is focused on this season", f"How we frame outcomes when work touches {activity}.", "priorities", d5[0]),
                _blog_post("Starting together: timelines and stakeholders", "What we ask for early so the first milestones stay realistic.", "kickoff", d5[1]),
                _blog_post("Review gates before client-facing delivery", "Internal checks we run so handoffs stay clean.", "reviews", d5[2]),
                _blog_post("Documentation habits that survive turnover", "Runbooks, owners, and where decisions live.", "docs", d5[3]),
                _blog_post("Risk logs: cheaper than surprise retros", "How we surface dependencies early without bloating the plan.", "risk-logs", d5[4]),
            ],
        )

    if vid != "news":
        _rebuild_blog_page_groups(merged, 3)

    merged.setdefault(
        "faq_page_intro",
        merged.get("faq_page_sub", f"Answers to common questions about {name}."),
    )
