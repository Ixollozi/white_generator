from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from datetime import date, timedelta
from typing import Any
from xml.sax.saxutils import escape

from core.content_dates import as_of_year, past_dates_spread
from core.person_names import pick_full_name, site_key_from_brand
from core.prose_vary import (
    apply_blog_post_depth_pass,
    apply_inject_to_random_html_paragraphs,
    massage_first_html_paragraph,
    news_local_anchor_sentence,
    pick_register_for_blog_post,
    prose_chatty_strength,
    prose_humanize_enabled,
    prose_micro_imperfections_enabled,
    vary_first_section_plain_shape,
    wrap_paragraph_html,
)

# Reputable external sources (real URLs) for citations and "Sources" blocks.
CURATED_SOURCES: list[dict[str, str]] = [
    {
        "title": "Digital news consumption — trend data",
        "url": "https://www.pewresearch.org/topic/news-habits-media/",
        "org": "Pew Research Center",
    },
    {
        "title": "Journalism, trust and safety (report hub)",
        "url": "https://www.unesco.org/en/journalism",
        "org": "UNESCO",
    },
    {
        "title": "World Economic Outlook (IMF)",
        "url": "https://www.imf.org/en/Publications/WEO",
        "org": "International Monetary Fund",
    },
    {
        "title": "WHO health topics & evidence briefs",
        "url": "https://www.who.int/health-topics",
        "org": "World Health Organization",
    },
    {
        "title": "World Bank — data & research",
        "url": "https://www.worldbank.org/en/research",
        "org": "World Bank",
    },
    {
        "title": "Reuters — World News",
        "url": "https://www.reuters.com/world/",
        "org": "Reuters",
    },
    {
        "title": "AP News — Fact checking",
        "url": "https://apnews.com/hub/ap-fact-check",
        "org": "The Associated Press",
    },
    {
        "title": "Nature — News & comment",
        "url": "https://www.nature.com/news",
        "org": "Nature",
    },
    {
        "title": "Science — News",
        "url": "https://www.science.org/news",
        "org": "Science (AAAS)",
    },
    {
        "title": "EU — Press corner",
        "url": "https://ec.europa.eu/commission/presscorner/home/en",
        "org": "European Commission",
    },
    {
        "title": "OECD — Publications",
        "url": "https://www.oecd.org/publications/",
        "org": "OECD",
    },
    {
        "title": "UN News",
        "url": "https://news.un.org/en",
        "org": "United Nations",
    },
]

NEWS_CATEGORIES: tuple[str, ...] = (
    "Technology",
    "Business",
    "World",
    "Science",
    "Politics",
    "Culture",
    "Health",
)

# Headline seeds — category must match NEWS_CATEGORIES.
_ARTICLE_BLUEPRINTS: list[tuple[str, str]] = [
    ("Inside the chip supply chain's quiet recalibration", "Technology"),
    ("Why city budgets are bracing for a colder bridge season", "Business"),
    ("Field note: how aid routes shift when borders tighten", "World"),
    ("Heat records aren't hype — here's how we quantify them", "Science"),
    ("Local races are drawing national money — and new rules", "Politics"),
    ("Streaming rights reshaped the festival circuit — what's next", "Culture"),
    ("The patchwork of AI disclosure laws — a reader's map", "Technology"),
    ("Small exporters are hedging currency risk differently now", "Business"),
    ("Correspondents on the ground: what 'verified' actually costs", "World"),
    ("A public lab opened its notebooks — early lessons", "Science"),
    ("Redistricting fights moved to spreadsheets — and court dockets", "Politics"),
    ("Museums are lending more, owning less — the fine print", "Culture"),
    ("Cyber incident disclosures: what changed after the last wave", "Technology"),
    ("Interest rates meets rent: the spreadsheet editors see", "Business"),
    ("Diplomatic language vs. satellite evidence — parsing both", "World"),
    ("Clinical trial transparency — why timelines slip in public view", "Science"),
    ("Coalitions form earlier now — ground organizers explain why", "Politics"),
    ("Indie venues and insurance — the boring clause that mattered", "Culture"),
    ("Cloud outages rippled through hospitals — a timeline", "Technology"),
    ("Venture debt isn't glamorous; here's who uses it", "Business"),
    ("ER wait times and triage protocols — what the data actually says", "Health"),
    ("Drug shortage ripples reach community pharmacies first", "Health"),
    ("Public health dashboards: lag, bias, and what readers should trust", "Health"),
]

# Short news / deep analysis / opinion column — shapes structure and length.
NEWS_ARTICLE_KINDS: tuple[str, ...] = ("news", "analysis", "column")

# Rubric blurbs for category index pages (news vertical).
NEWS_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Technology": "Platforms, security, infrastructure, and the policies that shape how systems fail and recover.",
    "Business": "Markets, public finance, trade, and the spreadsheets behind the headlines.",
    "World": "Field reporting, verification, and cross-border stories with named sourcing.",
    "Science": "Studies, data, replication, and the distance between press releases and methods.",
    "Politics": "Campaigns, courts, coalitions, and procedural calendars that decide outcomes.",
    "Culture": "Rights, venues, licensing, and the economics of how culture reaches audiences.",
    "Health": "Clinical evidence, access, and public health — with clear limits on what we can claim.",
}


def _a(url: str, text: str) -> str:
    safe_u = escape(url, {"\"": "&quot;"})
    return (
        f'<a href="{safe_u}" rel="nofollow noopener noreferrer" target="_blank">{escape(text)}</a>'
    )


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _trim_slug_at_word_boundary(s: str, max_len: int) -> str:
    s = (s or "").strip("-")
    if not s:
        return "story"
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    if cut.endswith("-"):
        t = cut[:-1].strip("-")
        return t or "story"
    last = cut.rfind("-")
    min_keep = max(14, max_len // 3)
    if last >= min_keep:
        return cut[:last].strip("-") or cut.strip("-")
    return cut.strip("-") or "story"


def _slugify_ascii(text: str, *, max_len: int = 64) -> str:
    s = (text or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _NON_ALNUM.sub("-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        return "story"
    if len(s) > max_len:
        s = _trim_slug_at_word_boundary(s, max_len)
    return s.strip("-") or "story"


def _pick_sources(rng: random.Random, k: int = 4) -> list[dict[str, str]]:
    pool = list(CURATED_SOURCES)
    rng.shuffle(pool)
    return [dict(x) for x in pool[:k]]


def _stats_snippets(category: str, rng: random.Random) -> list[str]:
    """Plausible, clearly attributed numeric texture (links added separately)."""
    vid = category.strip()
    pools: dict[str, list[str]] = {
        "Technology": [
            "Industry filings show outage-related downtime is increasingly clustered in Q4 windows, often 18-36 hours at the median before failover holds.",
            "Patch adoption surveys across enterprise panels routinely show two-week rollout tails even when severity scores look urgent on paper.",
            "Cloud migration audits reveal egress cost overruns of 15-40 percent above initial projections within the first 18 months.",
            "Firmware vulnerability disclosure timelines averaged 47 days longer for embedded systems than for consumer-facing software in comparable audits.",
            "Container orchestration incidents that cascaded across availability zones accounted for a growing share of high-severity post-mortems last year.",
        ],
        "Business": [
            "Treasury desks model a 120-190 basis-point swing sensitivity on short-dated hedges when invoicing crosses two currencies.",
            "Municipal budget officers in comparable metros often keep 4-7 percent contingency lines when bridge revenue depends on a volatile feeder tax.",
            "Working capital cycle compression of 8-14 days has been documented across mid-market suppliers since trade credit terms shortened.",
            "Commercial lease escalation clauses indexed to CPI diverged from operator revenue growth by 3-6 percentage points in recent renewal cycles.",
            "Accounts receivable aging past 90 days increased 22 percent year-over-year in sectors with concentrated buyer bases.",
        ],
        "World": [
            "Relief coordinators describe 12-28 hour clearance variability at busy crossings when documentation rules change mid-week.",
            "Field correspondents budget 30-45 percent more time for verification on stories involving satellite corroboration versus single-source claims.",
            "Translation-related ambiguities in multilateral agreement texts have led to interpretive disputes in at least four recent trade negotiations.",
            "Consular processing backlogs vary by a factor of three between posts in the same region, creating uneven refugee resettlement timelines.",
            "Sanctions compliance costs for mid-size firms have risen 18-30 percent annually as jurisdictional overlap increases.",
        ],
        "Science": [
            "Instrument teams publishing open methodology see 3-6 times more downstream citations within 18 months, a consistent pattern in public lab releases.",
            "Heat extreme analysis often blends station data with reanalysis grids; deltas of 0.3-0.8 degrees between products must be explained to readers.",
            "Pre-registration adoption rates in clinical research have doubled since 2018, but adherence to registered protocols varies by sponsor type.",
            "Data-sharing compliance among federally funded studies reached 61 percent in the most recent audit, up from 34 percent five years prior.",
            "Reproducibility assessments in computational biology found that 40 percent of published workflows could not be re-executed without author assistance.",
        ],
        "Politics": [
            "Campaign finance filings in parallel races can show 20-40 percent of spend arriving in the final 18 days before election day.",
            "Coalition bargaining in multi-party locals regularly runs 6-14 session nights; reporters track vote counts rather than momentum narratives.",
            "Digital ad spending in competitive state legislative races grew 55 percent cycle-over-cycle while disclosure requirements remained unchanged.",
            "Voter registration list maintenance processes flagged 2-5 percent of records as potentially obsolete, but false-positive rates varied sharply by algorithm.",
            "Early vote share as a percentage of total ballots cast increased in 38 of 50 states over the past two general election cycles.",
        ],
        "Culture": [
            "Independent venues report insurance renewals climbing 15-35 percent after loss events in their postcode clusters.",
            "Rights deals that bundle territorial windows can shift festival line-ups 8-16 months ahead; artists learn the calendar before fans do.",
            "Archive digitization grant applications outnumber available funding by a ratio of roughly 4-to-1 in recent national humanities cycles.",
            "Performing arts payroll taxes as a share of total production costs rose 8-12 percent in jurisdictions that reclassified contractor roles.",
            "International co-production treaty incentives reduced per-title localization costs by an estimated 10-18 percent for qualifying distributors.",
        ],
        "Health": [
            "Hospital capacity dashboards often lag real-time bed availability by 12-36 hours, complicating surge planning during seasonal peaks.",
            "Pharmacy benefit managers report generic substitution rates above 90 percent for common chronic medications in comparable markets.",
            "Clinical guideline updates propagate unevenly; primary care adoption can trail specialty consensus by several publication cycles.",
            "Public health surveillance systems show 2-5 day reporting delays for notifiable conditions, varying sharply by jurisdiction.",
            "Telehealth utilization stabilized post-pandemic at roughly double pre-2020 baselines for routine follow-up visits in insured populations.",
        ],
    }
    opts = list(pools.get(vid) or pools["World"])
    rng.shuffle(opts)
    return opts[:2]


_NEWS_AUTHOR_SEEDS: dict[str, list[tuple[str, str, str]]] = {
    "en": [
        (
            "Jordan Ellis",
            "Technology editor",
            "Covers platforms, security, and disclosure policy — prefers filings and depositions over anonymous posts.",
        ),
        (
            "Samira Mbeki",
            "Business correspondent",
            "Specializes in municipal finance and trade data — the spreadsheets that actually move deadlines.",
        ),
        (
            "Noah Chen",
            "World desk lead",
            "Runs field verification: two independent paths for any safety-relevant claim, always with a named editor.",
        ),
        (
            "Anika Larsen",
            "Science reporter",
            "Tracks replication efforts, open-data mandates, and the gap between press releases and peer review.",
        ),
        (
            "Marcus Reeves",
            "Politics correspondent",
            "Follows redistricting litigation, campaign finance disclosures, and coalition bargaining at the local level.",
        ),
        (
            "Lina Torres",
            "Culture and policy editor",
            "Reports on licensing economics, venue regulation, and the institutional decisions that shape cultural access.",
        ),
        (
            "Dr. Priya Nandakumar",
            "Health correspondent",
            "Covers clinical evidence, public health data, and the gap between guideline updates and what patients see in practice.",
        ),
    ],
    "fr": [
        (
            "Julien Morel",
            "Rédacteur technologies",
            "Couvre plateformes, sécurité et transparence réglementaire — privilégie les dossiers publics plutôt que les rumeurs anonymes.",
        ),
        (
            "Amélie Fontaine",
            "Correspondante économie",
            "Spécialisée dans les finances locales et les données d'échanges — les tableurs qui font vraiment bouger les échéances.",
        ),
        (
            "Karim Benali",
            "Chef du desk monde",
            "Pilote la vérification sur le terrain : deux sources indépendantes pour tout fait sensible, avec rédacteur nommé.",
        ),
        (
            "Claire Dubois",
            "Reporter sciences",
            "Suit la reprise d'études, l'open data et l'écart entre communiqués et méthodologie publiée.",
        ),
        (
            "Thomas Girard",
            "Correspondant politique",
            "Suit le financement des campagnes, le découpage électoral et les négociations de coalitions locales.",
        ),
        (
            "Élise Marchand",
            "Rédactrice culture et régulation",
            "Couvre droits, salles et politiques publiques qui façonnent l'accès à la culture.",
        ),
        (
            "Dr. Inès Okonkwo",
            "Correspondante santé",
            "Met l'accent sur les données cliniques et sanitaires et sur le délai entre recommandations et pratique patient.",
        ),
    ],
    "es": [
        (
            "Javier Ortega",
            "Editor de tecnología",
            "Cubre plataformas, ciberseguridad y marcos regulatorios — prioriza expedientes públicos frente a filtraciones anónimas.",
        ),
        (
            "Lucía Fernández",
            "Corresponsal de economía",
            "Se especializa en finanzas municipales y datos comerciales: las hojas de cálculo que marcan los plazos.",
        ),
        (
            "Mateo Silva",
            "Jefe de internacional",
            "Coordina verificación en terreno: dos rutas independientes para hechos sensibles, siempre con editor nombrado.",
        ),
        (
            "Elena Navarro",
            "Reportera de ciencias",
            "Sigue la replicación, los mandatos de datos abiertos y la distancia entre notas de prensa y revisión por pares.",
        ),
        (
            "Andrés Molina",
            "Corresponsal político",
            "Cubre litigio electoral, financiación de campañas y negociación de coaliciones locales.",
        ),
        (
            "Carmen Reyes",
            "Editora de cultura y políticas",
            "Informa sobre licencias, espacios y decisiones institucionales que condicionan el acceso cultural.",
        ),
        (
            "Dra. Rosa Villanueva",
            "Corresponsal de salud",
            "Enfoca la evidencia clínica y sanitaria y la brecha entre guías actualizadas y lo que ven los pacientes.",
        ),
    ],
}


def build_news_authors(
    rng: random.Random,
    brand_name: str,
    geo_profile: dict[str, Any] | None = None,
    brand: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    lang = str((geo_profile or {}).get("language") or "en").strip().lower()
    if lang.startswith("fr"):
        key = "fr"
    elif lang.startswith("es"):
        key = "es"
    else:
        key = "en"
    seeds = list(_NEWS_AUTHOR_SEEDS[key])
    rng.shuffle(seeds)
    take = rng.choice([3, 4, 5])
    sk = site_key_from_brand(brand or {})
    authors: list[dict[str, Any]] = []
    for i, (_seed_name, title, bio) in enumerate(seeds[:take]):
        bct = str((brand or {}).get("country") or "").strip() or None
        name = pick_full_name(sk, f"newsdesk|{key}|{i}", country=bct)
        slug = _slugify_ascii(name, max_len=36)
        aid = f"author-{i + 1}"
        authors.append(
            {
                "id": aid,
                "slug": slug,
                "name": name,
                "title": title,
                "bio": bio,
                "photo_src": "",
                "article_anchors": [],
            },
        )
    return authors


def _strip_trailing_parenthetical_title(title: str) -> str:
    s = (title or "").strip()
    if not s.endswith(")") or "(" not in s:
        return s
    depth = 0
    start = -1
    for j in range(len(s) - 1, -1, -1):
        if s[j] == ")":
            depth += 1
        elif s[j] == "(":
            depth -= 1
            if depth == 0:
                start = j
                break
    if start <= 0 or s[start - 1] not in " \t":
        return s
    return s[: start - 1].strip() or s


def _short_hash_token(key: str, *, n: int = 7) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:n]


def _unique_slug_seen(base: str, seen: set[str], *, max_len: int = 72) -> str:
    if base not in seen:
        return base
    n = 0
    candidate = base
    while candidate in seen:
        n += 1
        suffix = _short_hash_token(f"{base}|{n}")
        candidate = _slugify_ascii(f"{base}-{suffix}", max_len=max_len).strip("-") or suffix
    return candidate


def _slug_anchor(title: str, idx: int) -> str:
    base = _slugify_ascii(_strip_trailing_parenthetical_title(title), max_len=68)
    if not base or base == "story":
        base = _slugify_ascii(f"report-{idx}", max_len=40)
    return _trim_slug_at_word_boundary(base, 72)


def _comments_for_post(
    rng: random.Random,
    city: str,
    post_title: str,
    author_names: list[str] | None = None,
) -> list[dict[str, str]]:
    loc = city or "the area"
    t_short = (post_title or "this")[:35]
    pool = [
        ("M. Dray", f"This piece on {t_short} needed the numbers — thank you."),
        ("R. Velasquez", f"Shared this with our team in {loc}; the sourcing helps."),
        ("I. Park", "Subsection headers made it scannable. Good editorial choice."),
        ("L. Garrett", "Corrections at the top build trust. Noted for our own practice."),
        ("S. Lindberg", f"Would a glossary help newer readers follow {t_short}?"),
        ("A. Farah", f"Sources section on {t_short} is thorough. Good links."),
        ("J. Murata", f"Sent this to colleagues covering {t_short} in {loc}."),
        ("D. Kostic", f"Primary documents linked directly — more outlets should do this."),
        ("N. Pham", f"The timeline section on {t_short} helped me catch up quickly."),
        ("B. Alvarez", "This level of detail saves research time. Bookmarked."),
        ("C. Hartley", f"Balanced take on {t_short}. Appreciated the institutional context."),
        ("W. Sato", f"Cross-referencing {t_short} with our internal data — your figures track."),
        ("F. Osei", "Good distinction between confirmed and contested claims."),
        ("K. Brandt", f"We cited your reporting on {t_short} in a policy brief last week."),
        ("T. Novak", "The methodology notes add credibility. Keep publishing those."),
        ("H. Mendes", f"Readers in {loc} needed this context on {t_short}."),
        ("E. Strand", "Wish more newsrooms disclosed when sources decline comment."),
        ("P. Ricci", f"The regional angle on {t_short} is underreported elsewhere."),
        ("V. Zheng", "Appreciate the update timestamps on corrections."),
        ("G. Holm", f"Forwarded to my students as an example of sourced {t_short} coverage."),
    ]
    blocked_surnames: set[str] = set()
    for nm in (author_names or []):
        parts = nm.strip().split()
        if parts:
            blocked_surnames.add(parts[-1].lower())
    safe_pool = [
        (n, t) for n, t in pool
        if not any(s in n.lower() for s in blocked_surnames)
    ]
    if len(safe_pool) < 3:
        safe_pool = pool
    k = rng.choice([2, 3, 3, 4])
    rng.shuffle(safe_pool)
    out: list[dict[str, str]] = []
    for i in range(min(k, len(safe_pool))):
        name, txt = safe_pool[i]
        days = 1 + rng.randint(0, 9)
        out.append(
            {
                "author": name,
                "text": txt,
                "date_ago": f"{days}d ago",
            },
        )
    return out


def _author_for_news_category(authors: list[dict[str, Any]], category: str, fallback_idx: int) -> dict[str, Any]:
    cat = (category or "").strip()
    needles: tuple[str, ...] = {
        "Technology": ("technology", "technolog", "tecnolog"),
        "Business": ("business", "économ", "econom", "negocios"),
        "World": ("world", "monde", "mundial", "internacional", "international"),
        "Science": ("science", "scient", "ciencias"),
        "Politics": ("politics", "politique", "polític", "politic"),
        "Culture": ("culture", "cultura"),
        "Health": ("health", "santé", "salud"),
    }.get(cat, ())
    if needles:
        for a in authors:
            title = str(a.get("title") or "").lower()
            if any(n in title for n in needles):
                return a
    return authors[fallback_idx % len(authors)] if authors else {}


def _title_tokens(title: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", (title or "").lower())
    stop = frozenset(
        "a an the and or for to of in on at by is are was were be been being it its this that these those with from as".split()
    )
    return {w for w in raw if len(w) > 2 and w not in stop}


def _tags_for_post(
    rng: random.Random,
    category: str,
    title: str,
    geo_profile: dict[str, Any] | None = None,
) -> list[str]:
    cat = (category or "").strip()
    pools: dict[str, list[str]] = {
        "Technology": ["APIs", "Security", "Cloud", "Privacy", "Regulation", "Enterprise", "Open source"],
        "Business": ["Markets", "Finance", "Trade", "Labor", "Real estate", "Policy"],
        "World": ["Diplomacy", "Aid", "Borders", "Conflict", "Migration", "Verification"],
        "Science": ["Research", "Data", "Climate", "Health research", "Peer review", "Labs"],
        "Politics": ["Elections", "Campaigns", "Courts", "Legislatures", "Local government"],
        "Culture": ["Arts", "Media", "Film", "Music", "Venues", "Licensing"],
        "Health": ["Public health", "Hospitals", "Pharma", "Clinical", "Insurance", "Outcomes"],
    }
    pool = list(pools.get(cat, pools["World"]))
    rng.shuffle(pool)
    tags: list[str] = []
    for t in pool[:3]:
        if t not in tags:
            tags.append(t)
    for tok in list(_title_tokens(title))[:4]:
        pretty = tok[:1].upper() + tok[1:] if tok else tok
        if pretty and pretty not in tags and len(tags) < 6:
            tags.append(pretty)
    seeds = (geo_profile or {}).get("topic_seeds") if isinstance(geo_profile, dict) else None
    if isinstance(seeds, list) and seeds and len(tags) < 6 and rng.random() < 0.42:
        s = str(rng.choice(seeds)).strip()
        if s and s not in tags:
            tags.append(s)
    return tags[:6]


def _word_count_html_sections(html_secs: list[dict[str, Any]]) -> int:
    n = 0
    for sec in html_secs:
        for block in sec.get("paragraphs_html") or []:
            if isinstance(block, str):
                n += len(re.sub(r"<[^>]+>", " ", block).split())
    return n


def _related_news_posts(
    posts: list[dict[str, Any]],
    post: dict[str, Any],
    *,
    k: int = 5,
) -> list[dict[str, Any]]:
    anchor = str(post.get("anchor") or "")
    cat = str(post.get("category") or "")
    ptags = set(post.get("tags") or [])
    ptoks = _title_tokens(str(post.get("title") or ""))
    pdate = str(post.get("date_iso") or "")
    scored: list[tuple[float, dict[str, Any]]] = []
    for other in posts:
        oa = str(other.get("anchor") or "")
        if not oa or oa == anchor:
            continue
        s = 0.0
        if str(other.get("category") or "") == cat:
            s += 3.0
        otags = set(other.get("tags") or [])
        s += 2.0 * len(ptags & otags)
        otoks = _title_tokens(str(other.get("title") or ""))
        s += 0.8 * len(ptoks & otoks)
        od = str(other.get("date_iso") or "")
        if pdate and od:
            try:
                d0 = date.fromisoformat(pdate[:10])
                d1 = date.fromisoformat(od[:10])
                days = abs((d0 - d1).days)
                if days <= 45:
                    s += 1.5
                elif days <= 120:
                    s += 0.5
            except ValueError:
                pass
        scored.append((s, other))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for sc, o in scored[:k]:
        if sc <= 0 and len(out) >= 2:
            break
        out.append(
            {
                "title": o.get("title"),
                "anchor": o.get("anchor"),
                "category": o.get("category"),
                "excerpt": (str(o.get("excerpt") or ""))[:200],
            },
        )
    return out


def _read_minutes_from_words(words: int) -> int:
    return max(1, int(round(words / 220.0)))


def _view_count_for_post(rng: random.Random, words: int, date_iso: str) -> int:
    base = 800 + words * 2 + rng.randint(0, 2400)
    try:
        d = date.fromisoformat((date_iso or "")[:10])
        age_days = max(0, (date.today() - d).days)
    except ValueError:
        age_days = 60
    return int(base + age_days * rng.randint(8, 28) + rng.randint(0, 900))


def _article_sections(
    rng: random.Random,
    brand_name: str,
    city: str,
    title: str,
    category: str,
    excerpt: str,
    sources: list[dict[str, str]],
    article_kind: str,
) -> list[dict[str, Any]]:
    loc = city or "this region"
    c0, c1 = sources[0], sources[1] if len(sources) > 1 else sources[0]
    stats = _stats_snippets(category, rng)
    cat = category.strip()
    kind = (article_kind or "news").strip().lower()
    if kind not in NEWS_ARTICLE_KINDS:
        kind = "news"

    lede_pool: dict[str, list[str]] = {
        "Technology": [
            f"This piece traces the technical and regulatory layers behind {title.lower()[:60]} — where procurement documents and patch timelines tell a different story than press releases.",
            f"Readers in {loc} flagged gaps in how {title.lower()[:60]} has been reported. Here is what filings, audits, and on-the-record interviews actually show.",
            f"Enterprise infrastructure decisions rarely make headlines until something breaks. {brand_name} examines what the maintenance logs and vendor disclosures reveal.",
        ],
        "Business": [
            f"Municipal budgets and treasury filings paint a more detailed picture of {title.lower()[:60]} than quarterly earnings calls suggest.",
            f"Readers in {loc} asked how headline numbers connect to the spreadsheets their own teams maintain. This explainer bridges that gap.",
            f"Currency hedges, contingency lines, and revenue forecasts — the financial mechanics behind {title.lower()[:60]} that rarely surface in press briefings.",
        ],
        "World": [
            f"Field correspondents covering {title.lower()[:60]} describe verification challenges that single-source reporting cannot capture.",
            f"Border logistics, clearance timelines, and diplomatic signals — the ground-level reality behind {title.lower()[:60]} as observed in {loc}.",
            f"When official communiqués contradict satellite data, the reporting process itself becomes part of the story. This piece traces that tension.",
        ],
        "Science": [
            f"Open-methodology publications and reanalysis grids reveal nuances in {title.lower()[:60]} that summary headlines typically flatten.",
            f"Pre-registered protocols and instrument calibration notes shape how confidently we report on {title.lower()[:60]}.",
            f"Peer review timelines and replication efforts are essential context for understanding {title.lower()[:60]} — context we provide here.",
        ],
        "Politics": [
            f"Campaign finance filings and redistricting court dockets offer a sharper view of {title.lower()[:60]} than opinion surveys.",
            f"Ground organizers in {loc} describe coalition dynamics behind {title.lower()[:60]} that polling data alone cannot explain.",
            f"Procedural calendars, spending disclosures, and vote-count tracking — the structural forces behind {title.lower()[:60]}.",
        ],
        "Culture": [
            f"Rights licensing, insurance riders, and venue economics shape {title.lower()[:60]} months before audiences notice any change.",
            f"Readers asked how institutional decisions in {loc} affect {title.lower()[:60]}. The answer starts with lease renewals and territorial windows.",
            f"Attendance figures and curation timelines reveal pressures behind {title.lower()[:60]} that press kits rarely disclose.",
        ],
        "Health": [
            f"Clinical evidence and public health data tell a more cautious story about {title.lower()[:60]} than social feeds usually allow.",
            f"Readers in {loc} asked how {title.lower()[:60]} shows up in waiting rooms, pharmacies, and insurance explanations — not just press releases.",
            f"{brand_name} separates confirmed outcomes from contested claims on {title.lower()[:60]}, with attention to study design and reporting lags.",
        ],
    }
    lede = rng.choice(lede_pool.get(cat, lede_pool["World"]))
    if kind == "column":
        col_open = rng.choice(
            [
                "From the desk:",
                "Column:",
                "A view from the newsroom:",
                "Perspective —",
            ]
        )
        lede = f"{col_open} {lede}"
    elif kind == "analysis":
        lede = f"Analysis — {lede}"
    ex = excerpt.strip()
    if ex:
        lede = f"{lede} {ex}"

    s1 = stats[0] if stats else (
        "Editors tracked comparable beats across three news cycles to see what repeats — "
        "and what's genuinely new this time."
    )
    s2 = stats[1] if len(stats) > 1 else (
        "When institutions disagree, we show the delta in methods, not just the delta in headlines."
    )

    p_bulge = (
        f"{s1} "
        f"We cross-check filings, on-the-record interviews, and — when available — "
        f"independent datasets cited by {_a(c0['url'], c0['org'])} and {_a(c1['url'], c1['org'])}."
    )
    p_short = s2

    heading_mid_news = [
        "What we know right now",
        "The fastest facts, carefully sourced",
        "Key points at a glance",
        "How this story broke",
        "Verified details so far",
        "The headline in context",
    ]
    heading_mid_analysis = [
        "How we verified the key claims",
        "What changed since last cycle",
        "Where the official record diverges",
        "Source documents and data trails",
        "Comparing statements over time",
        "The timeline behind the headline",
        "Methodology and attribution notes",
        "What institutional filings show",
    ]
    heading_mid_column = [
        "Why this matters now",
        "The argument, briefly",
        "What we'd watch next",
        "Trade-offs the data hints at",
        "A dissenting read of the consensus",
        "What still isn't settled",
    ]
    if kind == "news":
        heading_pool_mid = list(heading_mid_news)
    elif kind == "column":
        heading_pool_mid = list(heading_mid_column)
    else:
        heading_pool_mid = list(heading_mid_analysis)

    heading_pool_local = [
        f"Implications for {loc}",
        f"What readers in {loc} should know",
        f"Regional context: {loc}",
        f"How this plays out in {loc}",
        f"Next milestones to watch in {loc}",
        f"The local angle for {loc}",
    ]
    rng.shuffle(heading_pool_mid)
    rng.shuffle(heading_pool_local)
    h_mid = heading_pool_mid[0] if heading_pool_mid else "Further context"
    h_local = heading_pool_local[0] if heading_pool_local else f"Context for {loc}"
    h_extra = ""
    if kind == "analysis" and len(heading_mid_analysis) > 1:
        pool_x = [h for h in heading_mid_analysis if h not in (h_mid, h_local)]
        rng.shuffle(pool_x)
        h_extra = pool_x[0] if pool_x else ""

    tl = title.lower()[:50]
    mid_para_pool = [
        f"On {tl}, we compare current statements with what the same officials said weeks ago, because contradiction is often the real story.",
        f"If a spokesperson on {tl} declines to go on record, we note that explicitly and link the public documents that speak for themselves.",
        f"Where we identify factual errors in our {cat.lower()} coverage, corrections are placed at the top with timestamps and brief explanations.",
        f"For {tl}, our editors required at least two independent verification paths before publication.",
        f"Earlier filings on this {cat.lower()} topic frequently contradict the framing of recent press conferences; we surface those deltas for readers.",
        f"Multi-source corroboration on {tl} helps us separate institutional messaging from verifiable signals in the data.",
        f"We reviewed three news cycles of comparable {cat.lower()} coverage to identify what genuinely changed versus what merely recycled prior reporting.",
        f"Documents cited in this piece on {tl} are linked directly so readers can assess our characterization against the originals.",
    ]
    rng.shuffle(mid_para_pool)

    local_para_pool = [
        f"For {tl} in {loc}, the next milestones include scheduled hearings, data releases, and budget votes on public calendars.",
        f"Readers in {loc} following this {cat.lower()} beat should watch for upcoming filings and committee sessions.",
        f"If you have primary documents related to {tl}, our contact page describes secure submission channels.",
        f"Local patterns in {loc} often amplify effects that national {cat.lower()} coverage presents as uniform; we track those regional variations.",
        f"Our annotation on {tl} distinguishes confirmed facts from contested claims and open questions.",
        f"Regulatory timelines specific to {loc} may differ from national averages on this {cat.lower()} topic; we note those differences when data is available.",
        f"Community stakeholders in {loc} have flagged aspects of {tl} that broader coverage overlooks; we follow up on those leads.",
    ]
    rng.shuffle(local_para_pool)

    paras_intro = [lede, p_bulge]
    if rng.random() < 0.5:
        paras_intro.append(p_short)
    else:
        paras_intro.insert(1, p_short)

    mid_n = 2 if kind == "news" else 3
    local_n = 2 if kind != "column" else 3
    out: list[dict[str, Any]] = [
        {"heading": "", "paragraphs": paras_intro},
        {"heading": h_mid, "paragraphs": mid_para_pool[:mid_n]},
        {"heading": h_local, "paragraphs": local_para_pool[:local_n]},
    ]
    if kind == "analysis" and h_extra:
        quote_pool = [
            f'One official involved in {tl} noted on the record that timelines "shift when clearance rules change mid-week" — a detail we verified against published schedules.',
            f"A subject-matter expert we interviewed described {tl} as requiring 'two independent paths' before their institution signs off — a standard {brand_name} mirrors in editing.",
            f"Readers should treat any single leaked document about {tl} as a fragment; we pair such material with contemporaneous filings whenever possible.",
        ]
        rng.shuffle(quote_pool)
        out.append({"heading": h_extra, "paragraphs": quote_pool[:2]})
    return out


def _wordish_html_paragraphs(
    sections: list[dict[str, Any]],
    rng: random.Random,
    category: str,
    *,
    target_min: int = 520,
    target_max: int = 820,
) -> tuple[list[dict[str, Any]], int]:
    """Returns sections with HTML paragraphs and approximate word count."""
    words = 0
    html_sections: list[dict[str, Any]] = []
    for sec in sections:
        heading = str(sec.get("heading") or "")
        paras = sec.get("paragraphs") or []
        html_paras: list[str] = []
        if isinstance(paras, str):
            paras = [paras]
        for p in paras:
            if not isinstance(p, str):
                continue
            t = p.strip()
            if not t:
                continue
            words += len(t.split())
            html_paras.append(f"<p>{escape(t)}</p>")
        html_sections.append({"heading": heading, "paragraphs_html": html_paras})
    cat = (category or "").strip()
    extra_pools: dict[str, list[str]] = {
        "Technology": [
            "Enterprise rollout timelines remain underreported: most security patches sit undeployed for weeks even after high-severity advisories.",
            "Vendor lock-in rarely appears in procurement headlines, but switching costs dominate multi-year TCO calculations for cloud infrastructure.",
            "Open-source audit transparency is improving, yet fewer than a third of critical libraries publish reproducible build artifacts.",
            "Incident response playbooks vary dramatically across organizations of similar size, making cross-industry benchmarks unreliable.",
            "Cloud egress fees are a recurring blind spot in migration budgets that only surface when workloads scale beyond initial estimates.",
            "Dependency chain vulnerabilities propagate faster than most security teams can triage when transitive packages are involved.",
            "Firmware update cycles for embedded systems often lag consumer software patches by months, creating persistent exposure windows.",
        ],
        "Business": [
            "Currency hedging decisions that seem routine in Q1 can swing quarterly earnings by double digits when volatility spikes later.",
            "Municipal bond watchers note that deferred maintenance liabilities often eclipse the headline deficit figures cities report.",
            "Supply chain resilience audits are shifting from annual reviews to continuous monitoring as disruption frequency climbs.",
            "Revenue recognition timing differences between GAAP and cash accounting can obscure the actual liquidity position for quarters.",
            "Commercial lease renewal negotiations increasingly include escalation clauses tied to indices that tenants rarely track proactively.",
            "Inventory carrying costs tend to be underestimated in quarterly reports because warehouse overhead is allocated across multiple line items.",
            "Trade credit terms between suppliers and retailers have shortened measurably since 2022, compressing working capital cycles.",
        ],
        "World": [
            "Humanitarian corridor negotiations often hinge on local intermediaries whose names never appear in summit communiques.",
            "Cross-border verification protocols vary widely; what counts as confirmed in one bureau may require a second source elsewhere.",
            "Diplomatic cables declassified years later frequently contradict the optimistic framing of real-time press briefings.",
            "Translation accuracy in multilateral negotiations introduces ambiguity that English-language coverage rarely acknowledges.",
            "Refugee processing timelines depend on consular staffing levels that fluctuate with host-country budget cycles.",
            "Sanctions enforcement mechanisms differ between jurisdictions, creating gaps that compliance teams must navigate individually.",
            "Local NGO capacity often determines aid delivery speed more than donor funding commitments announced at international summits.",
        ],
        "Science": [
            "Pre-registration of study protocols is growing, but selective outcome reporting still inflates effect sizes in meta-analyses.",
            "Replication efforts in social sciences have improved since 2015, though funding for confirmatory studies remains scarce.",
            "Open-access mandates are expanding, yet embargo periods still delay public access to taxpayer-funded research.",
            "Instrument calibration drift between measurement campaigns can introduce systematic errors that post-hoc correction only partially addresses.",
            "Statistical significance thresholds remain debated across disciplines, with some fields moving toward effect-size reporting instead.",
            "Collaboration networks in large-scale research create authorship attribution challenges that citation metrics do not fully capture.",
            "Data-sharing mandates from funding agencies are increasing, but standardized metadata formats remain inconsistent across repositories.",
        ],
        "Politics": [
            "Redistricting litigation timelines frequently compress into weeks, forcing courts to rule on maps they barely had time to review.",
            "Down-ballot races attract disproportionately less scrutiny despite controlling budgets that directly affect local services.",
            "Early voting data reveals turnout patterns that polls miss, particularly in communities with limited polling-place access.",
            "Lobbying disclosure requirements vary by jurisdiction, making comprehensive influence tracking across state lines difficult.",
            "Voter registration purge methodologies differ between states, with some relying on address-matching algorithms that produce false positives.",
            "Party platform language evolves between election cycles in ways that delegate-selection rules can amplify or suppress.",
            "Campaign ad spending on digital platforms now rivals broadcast in many districts, but disclosure requirements lag behind.",
        ],
        "Culture": [
            "Streaming residuals remain opaque for most working musicians, with royalty statements arriving months after plays accumulate.",
            "Independent gallery closures often trace back to lease renewals rather than attendance, a structural issue zoning rarely addresses.",
            "Festival curation increasingly depends on territorial licensing windows that audiences never see reflected in lineup announcements.",
            "Archival digitization projects compete for the same grant funding as new acquisitions, creating preservation backlogs.",
            "Performing arts insurance premiums have diverged sharply between venues with and without recent claims history.",
            "Translation and localization costs for international film distribution are rising as subtitle quality expectations increase.",
            "Nonprofit arts organizations face reporting requirements that consume administrative capacity disproportionate to grant size.",
        ],
        "Health": [
            "Prior authorization rules for specialty drugs changed in several plans this year; patients often learn at the pharmacy counter.",
            "Hospital quality metrics published quarterly can mask week-to-week strain during respiratory season surges.",
            "Generic shortages for common cardiovascular medications have persisted longer than manufacturers initially projected.",
            "Medicaid redetermination cycles created coverage gaps that community clinics are still quantifying in claims data.",
            "Telehealth parity laws vary by state; clinicians near jurisdictional borders may face different documentation requirements than peers elsewhere.",
            "Clinical trial diversity targets improved on paper, but enrollment still skews toward sites with existing research infrastructure.",
            "Insurance explanation-of-benefit documents remain difficult to parse even for financially literate households.",
        ],
    }
    pool = list(extra_pools.get(cat, extra_pools["World"]))
    rng.shuffle(pool)
    used: set[str] = set()
    for blob in pool:
        if words >= target_max:
            break
        if blob in used:
            continue
        used.add(blob)
        words += len(blob.split())
        html_sections[-1]["paragraphs_html"].append(f"<p>{escape(blob)}</p>")
    return html_sections, words


def _fill_dek(rng: random.Random, title: str, category: str, city: str = "") -> str:
    cat = category.strip()
    loc = city or "the region"
    t = title.strip()
    pools: dict[str, list[str]] = {
        "Technology": [
            f"How infrastructure shifts behind {t[:48]} affect procurement timelines and vendor decisions in {loc}.",
            f"A closer look at the regulatory and technical forces driving changes in {t[:48].lower()}.",
            f"What public filings, patch cycles, and enterprise audits reveal about {t[:48].lower()}.",
        ],
        "Business": [
            f"Budget pressures, hedging strategies, and what municipal data shows about {t[:48].lower()}.",
            f"The financial mechanics behind {t[:48].lower()} — and why treasury desks are adjusting now.",
            f"Revenue forecasts and spending patterns that explain {t[:48].lower()} in {loc}.",
        ],
        "World": [
            f"How verification protocols and field reporting shape coverage of {t[:48].lower()}.",
            f"Corridor access, diplomatic signals, and ground-level detail on {t[:48].lower()}.",
            f"What correspondents in {loc} observe about {t[:48].lower()} beyond official statements.",
        ],
        "Science": [
            f"Methodology, data transparency, and peer review context for {t[:48].lower()}.",
            f"How open-notebook practices and replication efforts inform {t[:48].lower()}.",
            f"What instrument data and pre-registered protocols show about {t[:48].lower()}.",
        ],
        "Politics": [
            f"Campaign filings, redistricting data, and organizing patterns behind {t[:48].lower()}.",
            f"How ground-level coalition work and court dockets shape {t[:48].lower()} in {loc}.",
            f"Voter data, spending disclosures, and procedural context for {t[:48].lower()}.",
        ],
        "Culture": [
            f"Licensing economics, venue logistics, and the fine print behind {t[:48].lower()}.",
            f"How rights deals and insurance clauses influence {t[:48].lower()} in {loc}.",
            f"Attendance data, lease dynamics, and curation pressures shaping {t[:48].lower()}.",
        ],
        "Health": [
            f"What clinical data and public health reporting show about {t[:48].lower()} — beyond anecdote.",
            f"How access, insurance rules, and capacity shape {t[:48].lower()} for patients in {loc}.",
            f"Evidence, limitations, and what providers watch next on {t[:48].lower()}.",
        ],
    }
    opts = pools.get(cat, pools["World"])
    return rng.choice(opts)


def enrich_news_vertical_content(
    merged: dict[str, Any],
    brand: dict[str, Any],
    rng: random.Random,
) -> None:
    """Attach long-form posts, authors, categories, trending lists for vertical=news."""
    name = str(brand.get("brand_name") or "Newsroom")
    city = str(brand.get("city") or "").strip()

    geo_profile = brand.get("geo_profile") if isinstance(brand.get("geo_profile"), dict) else {}
    authors = build_news_authors(rng, name, geo_profile, brand=brand)
    merged["news_authors"] = authors
    merged["blog_categories"] = list(NEWS_CATEGORIES)
    merged["footer_newsletter_blurb"] = (
        "Weekly digest — explainers, briefings, and the links we refused to bury."
    )
    fy = brand.get("founded_year")
    cy = as_of_year(brand)
    if fy is not None and str(fy).strip().isdigit():
        fy_txt = str(int(fy))
    else:
        decade = (cy // 10) * 10
        fy_txt = f"the {decade}s"
    merged["publication_origin_story"] = (
        f"{name} launched in {fy_txt} as a small newsroom tired of feeds "
        f"that prize velocity over verification. We built workflows for corrections, sourcing, and explainers — "
        f"the unglamorous spine readers lean on when complexity spikes."
    )
    merged["news_category_descriptions"] = dict(NEWS_CATEGORY_DESCRIPTIONS)

    blueprints = list(_ARTICLE_BLUEPRINTS)
    cap = merged.get("news_article_count")
    if cap is not None:
        try:
            n_cap = int(cap)
            if 1 <= n_cap < len(blueprints):
                blueprints = blueprints[:n_cap]
        except (TypeError, ValueError):
            pass
    n_posts = len(blueprints)
    dates = past_dates_spread(rng, n_posts, brand=brand)
    posts: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_anchors: set[str] = set()
    for i, (title, cat) in enumerate(blueprints):
        t = str(title).strip()
        if t.lower() in seen_titles:
            t = f"{t} (updates)"
        seen_titles.add(t.lower())
        anchor = _unique_slug_seen(_slug_anchor(t, i), seen_anchors)
        seen_anchors.add(anchor)
        display_d, iso_d = dates[i]
        author = _author_for_news_category(authors, cat, i)
        article_kind = str(merged.get("news_default_article_kind") or "").strip().lower()
        mix = merged.get("news_style_mix")
        if isinstance(mix, dict):
            kn = str(mix.get(str(i)) or mix.get(cat) or "").strip().lower()
            if kn in NEWS_ARTICLE_KINDS:
                article_kind = kn
        if article_kind not in NEWS_ARTICLE_KINDS:
            article_kind = NEWS_ARTICLE_KINDS[i % len(NEWS_ARTICLE_KINDS)]

        post_register = pick_register_for_blog_post(i, rng)

        short_band = rng.random() < 0.47
        if article_kind == "news":
            target_min, target_max = (500, 800) if short_band else (960, 1420)
        elif article_kind == "analysis":
            target_min, target_max = (1000, 1500) if not short_band else (520, 820)
        else:
            target_min, target_max = (620, 980) if short_band else (900, 1380)

        excerpt = _fill_dek(rng, t, cat, city)
        sources = _pick_sources(rng, 4)
        sections_raw = _article_sections(rng, name, city, t, cat, excerpt, sources, article_kind)
        html_secs, wc = _wordish_html_paragraphs(
            sections_raw, rng, cat, target_min=target_min, target_max=target_max
        )
        if prose_humanize_enabled(brand, merged):
            ch = prose_chatty_strength(brand, merged)
            mic = prose_micro_imperfections_enabled(brand, merged)
            vary_first_section_plain_shape(html_secs, rng)
            apply_inject_to_random_html_paragraphs(html_secs, brand, rng, max_touch=2)
            massage_first_html_paragraph(
                html_secs,
                rng,
                register=post_register,
                micro=mic,
                chatty_strength=ch,
            )
            apply_blog_post_depth_pass(
                html_secs,
                brand,
                rng,
                register=post_register,
                micro=mic,
                chatty_strength=ch,
            )
            if rng.random() < 0.34 and html_secs:
                paras0 = html_secs[0].get("paragraphs_html")
                if isinstance(paras0, list):
                    paras0.insert(1, wrap_paragraph_html(news_local_anchor_sentence(city, brand, rng)))
        _cat_fillers: dict[str, list[str]] = {
            "Technology": [
                f"Vendor disclosure timelines for incidents like {t[:40].lower()} remain inconsistent across jurisdictions.",
                "Patch rollout surveys show two-week tails even when severity scores suggest urgency on paper.",
                "Enterprise procurement decisions often lag behind the technical reality by one or two budget cycles.",
                f"Open-source audit logs related to this {cat.lower()} story are publicly available but rarely cited in mainstream coverage.",
                "Infrastructure post-mortems published by operators frequently contradict initial incident statements.",
                "Failover testing cadences vary widely; some teams exercise quarterly, others only after a major outage.",
            ],
            "Business": [
                f"Municipal budget officers tracking {t[:40].lower()} report contingency lines of 4-7 percent when revenue depends on volatile feeders.",
                "Treasury desks model basis-point swings on short-dated hedges differently depending on invoice currencies.",
                "Deferred maintenance liabilities often eclipse headline deficit figures in comparable metro budgets.",
                f"Bond market watchers note that stories like {t[:40].lower()} move credit default spreads before they move headlines.",
                "Supply chain resilience audits are shifting from annual reviews to continuous monitoring in many sectors.",
                "Revenue recognition timing can obscure the actual cash position by several quarters.",
            ],
            "World": [
                "Humanitarian corridor negotiations often hinge on local intermediaries not named in summit communiques.",
                f"Field correspondents covering {t[:40].lower()} budget additional time for multi-source verification.",
                "Cross-border documentation rules can change mid-week during escalating alerts, adding clearance variability.",
                "Diplomatic cables declassified years later frequently contradict the real-time press briefing framing.",
                "Relief logistics planners track crossing-point throughput hourly, not daily, during active crises.",
                "Satellite corroboration adds verification confidence but also extends publication timelines significantly.",
            ],
            "Science": [
                "Pre-registration of study protocols reduces selective outcome reporting but adoption remains uneven.",
                f"Instrument calibration notes relevant to {t[:40].lower()} are published in supplementary materials most readers skip.",
                "Replication funding remains scarce despite improved methodological standards since 2015.",
                "Open-access mandates are expanding, yet embargo periods still delay public access to taxpayer-funded findings.",
                "Effect size inflation in meta-analyses is a known issue that careful pre-registration helps address.",
                "Station data and reanalysis grids often show deltas that must be explained before headline conclusions.",
            ],
            "Politics": [
                "Campaign finance filings show 20-40 percent of spend arriving in the final 18 days of competitive races.",
                f"Coalition bargaining around {t[:40].lower()} typically runs multiple session nights before vote counts stabilize.",
                "Redistricting litigation timelines compress into weeks, forcing courts to rule on maps with minimal review.",
                "Down-ballot races receive disproportionately less scrutiny despite controlling budgets that affect local services directly.",
                "Early voting data reveals turnout patterns that traditional polls routinely miss in underserved communities.",
                "Ground organizers describe formation dynamics that polling snapshots cannot capture in real time.",
            ],
            "Culture": [
                "Independent venues report insurance renewal increases of 15-35 percent after loss events in their postcode cluster.",
                f"Rights deals influencing {t[:40].lower()} bundle territorial windows that shift lineups months before audiences notice.",
                "Streaming residuals remain opaque for working musicians, with royalty statements arriving months after plays accumulate.",
                "Gallery closures trace more often to lease renewal terms than to attendance figures.",
                "Festival curation depends on licensing windows that audiences never see reflected in lineup announcements.",
                "Venue capacity riders matter as much as headline insurance premiums for independent operators.",
            ],
            "Health": [
                f"Clinicians following {t[:40].lower()} note that payer rules and formulary tiers can change faster than clinical guidelines.",
                "Emergency department boarding times in comparable metros rose in the last measured quarter even as aggregate quality scores held steady.",
                "Pharmacy benefit managers increasingly require step therapy for specialty classes where cheaper alternatives exist.",
                "Public health dashboards for respiratory season often trail hospital census peaks by several days.",
                "Medicaid unwinding produced churn that community health centers are still capturing in intake data.",
                "Patients report confusion between in-network facilities and in-network physicians for the same episode of care.",
            ],
        }
        _pool = list(_cat_fillers.get(cat, _cat_fillers["World"]))
        rng.shuffle(_pool)
        _used: set[str] = set()
        for _fp in _pool:
            if wc >= target_max:
                break
            if _fp in _used:
                continue
            _used.add(_fp)
            html_secs[-1]["paragraphs_html"].append(f"<p>{escape(_fp)}</p>")
            wc += len(_fp.split())

        wc = _word_count_html_sections(html_secs)
        tags = _tags_for_post(rng, cat, t, geo_profile)
        read_minutes = _read_minutes_from_words(wc)
        view_count = _view_count_for_post(rng, wc, iso_d)
        image_alt = f"Illustration for {t[:72]} — {cat}, {city or 'regional'} desk."

        post = {
            "title": t,
            "dek": excerpt,
            "excerpt": excerpt[:280] + ("..." if len(excerpt) > 280 else ""),
            "category": cat,
            "article_kind": article_kind,
            "tags": tags,
            "word_count": wc,
            "read_minutes": read_minutes,
            "view_count": view_count,
            "anchor": anchor,
            "date": display_d,
            "date_iso": iso_d,
            "author_id": author["id"],
            "author_name": author["name"],
            "author_slug": author["slug"],
            "sources": sources,
            "article_sections_html": html_secs,
            "comments": _comments_for_post(
                rng, city, title,
                author_names=[a.get("name", "") for a in authors],
            ),
            "post_image_src": f"img/posts/{anchor}.jpg",
            "image_alt": image_alt,
        }
        posts.append(post)
        author["article_anchors"].append(anchor)

    for p in posts:
        p["related_posts"] = _related_news_posts(posts, p, k=5)

    merged["blog_posts"] = posts
    merged["blog_heading"] = merged.get("blog_heading") or "Latest coverage"
    merged["blog_intro"] = merged.get("blog_intro") or (
        f"Reporting and explainers from {name} — with dates, bylines, sources, and room for updates."
    )

    trending = [posts[i] for i in rng.sample(range(len(posts)), min(5, len(posts)))]
    popular = [posts[i] for i in rng.sample(range(len(posts)), min(5, len(posts)))]
    merged["trending_posts"] = [{"title": p["title"], "anchor": p["anchor"], "category": p["category"]} for p in trending]
    merged["popular_posts"] = [{"title": p["title"], "anchor": p["anchor"], "category": p["category"]} for p in popular]

    posts_list = merged.get("blog_posts")
    if isinstance(posts_list, list):
        merged["blog_page_groups"] = [posts_list[i : i + 4] for i in range(0, len(posts_list), 4)]

    origin = (merged.get("publication_origin_story") or "").strip()
    body = (merged.get("about_body") or "").strip()
    if origin and origin not in body:
        merged["about_body"] = f"{origin} {body}".strip() if body else origin
