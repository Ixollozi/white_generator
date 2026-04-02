from __future__ import annotations

import datetime
import hashlib
import random
import re
import string
from typing import Any
from urllib.parse import quote_plus

from core.address_catalog import (
    pick_address_for_site,
    pick_districts_for_site,
    pick_geo_for_city,
    pick_surname,
    DISTRICTS,
    SURNAMES,
)
from core.geo_profile import merge_geo_into_brand
from core.money_locale import localize_money_labels


def _coerce_vertical_text(x: Any) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return "; ".join(f"{k}: {v}" for k, v in x.items())
    return str(x)


# Used only for explicit "brand_word" strategy — kept short to avoid TrueHVAC-style spam.
_PREFIXES = (
    "Ridge", "Maple", "Cedar", "Harbor", "Bay", "Stone", "Field", "Urban",
    "Metro", "Lakeview", "Riverside", "Parkside", "Westend", "Eastside",
)
_SUFFIXES = (
    "Reach", "Consult", "Solutions", "Digital", "Media", "Works", "Labs",
    "Group", "Partners", "Studio", "Hub", "Flow", "Edge", "Path",
    "Pro", "Point", "Services", "Collective", "Advisory", "Craft",
)

_NICHE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "cleaning": ("Cleaning", "Cleaning Co.", "Cleaning Services", "Janitorial", "Facility Care"),
    "dental": ("Dental", "Dental Care", "Dental Clinic", "Dentistry", "Dental Group"),
    "plumbing": ("Plumbing", "Plumbing Co.", "Plumbing Services", "Plumbing & Heating", "Drain Services"),
    "roofing": ("Roofing", "Roofing Co.", "Roofing Services", "Roofing & Siding", "Roof Pros"),
    "landscaping": ("Landscaping", "Lawn & Garden", "Landscape Design", "Grounds Care", "Outdoor Living"),
    "consulting": ("Consulting", "Advisors", "Advisory Group", "Consulting Group", "Strategy"),
    "moving": ("Moving", "Moving Co.", "Movers", "Moving & Storage", "Relocations"),
    "hvac": ("HVAC", "Heating & Cooling", "Climate Control", "Mechanical Services", "Air Systems"),
    "legal": ("Law", "Law Firm", "Legal", "Attorneys", "Law Group", "Legal Services"),
    "medical": ("Medical", "Health", "Medical Group", "Health Services", "Medical Centre"),
    "electrical": ("Electric", "Electrical", "Electrical Services", "Electric Co.", "Power Systems"),
    "auto_repair": ("Auto", "Auto Repair", "Automotive", "Auto Care", "Motor Works"),
    "real_estate": ("Realty", "Real Estate", "Properties", "Property Group", "Homes"),
    "accounting": ("Accounting", "CPA", "Bookkeeping", "Financial Services", "Tax Services"),
    "pest_control": ("Pest Control", "Exterminators", "Pest Solutions", "Pest Management", "Bug Free"),
    "fitness": ("Fitness", "Gym", "Training", "Athletics", "Strength & Conditioning"),
    "marketing_agency": ("Digital", "Marketing", "Creative", "Agency", "Media Group"),
    "cafe_restaurant": ("Kitchen", "Bistro", "Table", "Eatery", "Dining"),
    "clothing": ("Apparel", "Wear", "Clothing Co.", "Outfitters", "Supply Co."),
}

_CORPORATE_SUFFIXES: tuple[str, ...] = (
    "& Sons", "& Associates", "Group", "Solutions", "Co.", "Inc.", "LLC",
    "Services", "Partners", "Enterprises", "Holdings", "International",
)

# Weighted toward local/surname patterns; "compound" is low (was a major AI fingerprint).
_NAME_STRATEGY_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("surname_service", 24),
    ("district_niche", 22),
    ("abbreviation", 20),
    ("surname_group", 14),
    ("surname_sons_niche", 10),
    ("brand_word", 6),
    ("compound", 4),
)

# Regional short codes for abbreviation-style names (city from address peek).
_CITY_REGION_ABBREV: dict[str, tuple[str, ...]] = {
    "Toronto": ("GTA", "GTHA"),
    "Vancouver": ("GVA",),
    "Calgary": ("YYC",),
    "Montreal": ("MTL",),
    "Singapore": ("SG",),
    "Dublin": ("DUB",),
    "Sydney": ("SYD",),
    "Melbourne": ("MEL",),
}

_ABB_TAIL_WORDS: tuple[str, ...] = (
    "Comfort",
    "Mechanical",
    "Climate",
    "Air Systems",
    "HVAC",
    "Heating",
    "Services",
    "Climate Control",
)

_VERTICAL_CLIENT_TYPE: dict[str, str] = {
    "cleaning": "B2B",
    "marketing_agency": "B2B",
    "consulting": "B2B",
    "accounting": "B2B",
    "legal": "Both",
    "dental": "B2C",
    "medical": "B2C",
    "plumbing": "B2C",
    "roofing": "B2C",
    "hvac": "B2C",
    "electrical": "B2C",
    "landscaping": "B2C",
    "moving": "B2C",
    "pest_control": "B2C",
    "auto_repair": "B2C",
    "real_estate": "Both",
    "fitness": "B2C",
    "cafe_restaurant": "B2C",
    "clothing": "B2C",
    "news": "B2C",
}

_VERTICAL_TEAM_RANGE: dict[str, tuple[int, int]] = {
    "cleaning": (5, 18),
    "dental": (4, 12),
    "plumbing": (3, 10),
    "roofing": (4, 12),
    "landscaping": (4, 14),
    "consulting": (3, 8),
    "moving": (6, 20),
    "hvac": (4, 12),
    "legal": (3, 8),
    "medical": (5, 15),
    "electrical": (3, 10),
    "auto_repair": (3, 8),
    "real_estate": (3, 12),
    "accounting": (3, 7),
    "pest_control": (3, 8),
    "fitness": (4, 12),
    "marketing_agency": (4, 15),
    "cafe_restaurant": (5, 18),
    "clothing": (4, 12),
    "news": (5, 20),
}

_VERTICAL_PRICE_RANGE: dict[str, tuple[str, ...]] = {
    "cleaning": ("$80–$300 per visit", "$150–$500 per visit", "$200–$800 per visit"),
    "dental": ("$100–$500", "$150–$800", "$200–$1,200"),
    "plumbing": ("$80–$400", "$150–$600", "$200–$900"),
    "roofing": ("$3,000–$12,000", "$5,000–$20,000", "$8,000–$35,000"),
    "landscaping": ("$200–$2,000", "$500–$5,000", "$1,000–$10,000"),
    "consulting": ("$150–$300/hr", "$200–$500/hr", "Project-based"),
    "moving": ("$300–$1,500", "$500–$3,000", "$800–$5,000"),
    "hvac": ("$100–$500", "$200–$1,200", "$500–$5,000"),
    "legal": ("$200–$500/hr", "$250–$600/hr", "Retainer-based"),
    "medical": ("Varies by service", "$100–$500", "$150–$800"),
    "electrical": ("$75–$300", "$150–$600", "$200–$1,000"),
    "auto_repair": ("$80–$500", "$150–$1,200", "$200–$2,000"),
    "real_estate": ("Commission-based", "2.5%–5% commission", "Flat fee available"),
    "accounting": ("$100–$300/hr", "$150–$400/hr", "Monthly retainer"),
    "pest_control": ("$100–$400", "$150–$600", "$200–$800"),
    "fitness": ("$40–$80/mo", "$60–$120/mo", "$80–$200/mo"),
    "marketing_agency": ("$2,000–$5,000/mo", "$3,000–$10,000/mo", "$5,000–$20,000/mo"),
    "cafe_restaurant": ("$$", "$$$", "$$–$$$"),
    "clothing": ("$30–$150", "$50–$300", "$80–$500"),
    "news": ("Free", "Free with newsletter", "Ad-supported"),
}

_VERTICAL_LICENSES: dict[str, tuple[str, ...]] = {
    "cleaning": ("Licensed & Insured", "OSHA Compliant", "Green Seal Certified", "ISSA Member"),
    "dental": ("Licensed Dental Practice", "ADA Member", "State Board Certified"),
    "plumbing": ("Licensed Master Plumber", "Bonded & Insured", "Backflow Certified"),
    "roofing": ("Licensed Roofing Contractor", "Bonded & Insured", "GAF Certified", "OSHA 30 Trained"),
    "landscaping": ("Licensed Landscaper", "Insured", "ISA Certified Arborist"),
    "consulting": ("Certified Management Consultant", "ISO 9001 Compliant"),
    "moving": ("Licensed & Insured", "DOT Registered", "BBB Accredited"),
    "hvac": ("EPA 608 Certified", "NATE Certified", "Licensed HVAC Contractor", "Bonded & Insured"),
    "legal": ("Licensed to Practice", "Bar Association Member", "Peer Review Rated"),
    "medical": ("Licensed Medical Practice", "Board Certified", "HIPAA Compliant"),
    "electrical": ("Licensed Master Electrician", "Bonded & Insured", "ESA Certified"),
    "auto_repair": ("ASE Certified", "Licensed Auto Repair", "AAA Approved"),
    "real_estate": ("Licensed Real Estate Broker", "MLS Member", "REALTOR Association Member"),
    "accounting": ("CPA Licensed", "QuickBooks ProAdvisor", "IRS Enrolled Agent"),
    "pest_control": ("Licensed Pest Control Operator", "EPA Registered", "NPMA Member"),
    "fitness": ("Certified Personal Trainers", "CPR/AED Certified", "NSCA Affiliate"),
    "marketing_agency": ("Google Partner", "Meta Business Partner", "HubSpot Certified"),
    "cafe_restaurant": ("Food Handler Certified", "Health Department Inspected", "Liquor Licensed"),
    "clothing": ("Certified B Corporation", "Fair Trade Certified"),
    "news": ("SPJ Member", "Registered Media Outlet"),
}

_VERTICAL_CERTIFICATIONS: dict[str, tuple[str, ...]] = {
    "cleaning": ("CIMS Certified", "GBAC STAR", "GS-42 Certified"),
    "dental": ("Invisalign Provider", "CEREC Trained", "Sedation Certified"),
    "plumbing": ("Water Heater Specialist", "Gas Fitter Licensed", "Trenchless Certified"),
    "roofing": ("CertainTeed SELECT", "Owens Corning Preferred", "TPO Certified"),
    "hvac": ("Carrier Factory Authorized", "Lennox Premier Dealer", "Energy Star Partner"),
    "electrical": ("EV Charger Installer", "Solar Panel Certified", "Smart Home Specialist"),
    "auto_repair": ("Hybrid/EV Specialist", "Emissions Testing Station", "OEM Parts Dealer"),
    "pest_control": ("QualityPro Certified", "GreenPro Certified", "K-9 Inspection Team"),
}


def _pick_strategy_weighted(rng: random.Random) -> str:
    opts = [s for s, _ in _NAME_STRATEGY_WEIGHTS]
    wts = [w for _, w in _NAME_STRATEGY_WEIGHTS]
    return rng.choices(opts, weights=wts, k=1)[0]


def _initials_from_identity(site_identity: str, k: int = 3) -> str:
    h = hashlib.sha256(f"ini|{site_identity}".encode()).hexdigest().upper()
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    out: list[str] = []
    for ch in h:
        if ch in letters and ch not in out:
            out.append(ch)
        if len(out) >= k:
            break
    while len(out) < k:
        out.append(letters[len(out) % len(letters)])
    return "".join(out)


def _generate_brand_name(
    rng: random.Random,
    vertical_id: str,
    city: str,
    site_identity: str,
    theme_pre: list[str] | None,
    theme_suf: list[str] | None,
) -> str:
    # Theme pools often recreate SparkleLane-style names; use them only part of the time.
    if (
        isinstance(theme_pre, list)
        and isinstance(theme_suf, list)
        and theme_pre
        and theme_suf
        and rng.random() < 0.32
    ):
        return str(rng.choice(theme_pre)) + str(rng.choice(theme_suf))

    strategy = _pick_strategy_weighted(rng)
    surname = pick_surname(site_identity)
    niche_pool = _NICHE_SUFFIXES.get(vertical_id, ())
    generic_niche = ("Services", "Solutions", "Group", "Co.")

    if strategy == "surname_service" and niche_pool:
        suf = rng.choice(niche_pool)
        return f"{surname} {suf}"

    if strategy == "district_niche" and niche_pool:
        districts = DISTRICTS.get(city, ())
        if districts:
            district = rng.choice(districts)
            suf = rng.choice(niche_pool)
            return f"{district} {suf}"
        return f"{surname} {rng.choice(niche_pool)}"

    if strategy == "abbreviation":
        # Mix: regional + service word, or initials + Mechanical/Comfort (TCS-style).
        if rng.random() < 0.45:
            reg_opts = _CITY_REGION_ABBREV.get(city, ())
            if reg_opts:
                abbrev = rng.choice(reg_opts)
                tail = rng.choice(_ABB_TAIL_WORDS)
                return f"{abbrev} {tail}"
        letters = _initials_from_identity(site_identity, k=rng.choice([2, 3]))
        tail = rng.choice(_ABB_TAIL_WORDS)
        if rng.random() < 0.35:
            corp = rng.choice(("Mechanical", "Group", "Services", "Co."))
            return f"{letters} {corp}"
        return f"{letters} {tail}"

    if strategy == "surname_group":
        corp = rng.choice(("& Associates", "Group", "Partners", "& Partners", "& Co.", "LLC"))
        if niche_pool and rng.random() < 0.4:
            suf = rng.choice(niche_pool)
            return f"{surname} {corp} {suf}"
        return f"{surname} {corp}"

    if strategy == "surname_sons_niche" and niche_pool:
        suf = rng.choice(niche_pool)
        if rng.random() < 0.55:
            return f"{surname} & Sons {suf}"
        return f"{surname} & Sons {rng.choice(('Co.', 'Inc.', 'Ltd.'))}"

    if strategy == "brand_word":
        return rng.choice(_PREFIXES) + rng.choice(_SUFFIXES)

    if strategy == "compound" and niche_pool:
        # Local-ish compound, not "True + HVAC"
        local = (
            f"{city} Metro {rng.choice(niche_pool)}"
            if city and rng.random() < 0.5
            else f"{rng.choice(_PREFIXES)} {rng.choice(niche_pool)}"
        )
        return local

    if niche_pool:
        return f"{surname} {rng.choice(niche_pool)}"
    return f"{surname} {rng.choice(generic_niche)}"

_DOMAIN_SAFE_RE = re.compile(r"[^a-z0-9]+")
_RE_CAN_POSTAL = re.compile(r"^[A-Z]\d[A-Z] \d[A-Z]\d$")
_RE_IE_EIRCODE = re.compile(r"^D\d{2} [A-Z]\d[A-Z]\d$")


def _random_local_part(rng: random.Random) -> str:
    n = rng.randint(4, 8)
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(n))


def _slug_domain(name: str) -> str:
    s = name.strip().lower()
    s = _DOMAIN_SAFE_RE.sub("", s)
    return s[:40] if s else "site"


def _pick_tld(rng: random.Random, tlds: list[str] | None) -> str:
    pool = [x for x in (tlds or []) if isinstance(x, str) and x.strip()]
    if not pool:
        pool = ["com", "net", "org"]
    return rng.choice(pool).lstrip(".").lower()

# Per-site typography (reduces identical Google Fonts fingerprint across exports).
_FONT_STACKS: tuple[tuple[str, str, str | None], ...] = (
    (
        "https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&display=swap",
        '"Source Sans 3", system-ui, sans-serif',
        None,
    ),
    (
        "https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,600;0,9..40,700;1,9..40,400&family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,700;1,9..144,400&display=swap",
        '"DM Sans", system-ui, sans-serif',
        '"Fraunces", Georgia, "Times New Roman", serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&display=swap",
        '"Manrope", system-ui, sans-serif',
        '"Newsreader", Georgia, serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Work+Sans:ital,wght@0,400;0,600;0,700;1,400&family=Bitter:ital,wght@0,400;0,600;0,700;1,400&display=swap",
        '"Work Sans", system-ui, sans-serif',
        '"Bitter", Georgia, serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Nunito+Sans:ital,opsz,wght@0,6..12,400;0,6..12,600;0,6..12,700;1,6..12,400&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&display=swap",
        '"Nunito Sans", system-ui, sans-serif',
        '"Playfair Display", Georgia, serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Lora:ital,wght@0,400;0,600;0,700;1,400&display=swap",
        '"Inter", system-ui, sans-serif',
        '"Lora", Georgia, serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap",
        '"Outfit", system-ui, sans-serif',
        None,
    ),
    (
        "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap",
        '"Plus Jakarta Sans", system-ui, sans-serif',
        None,
    ),
    (
        "https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap",
        '"Figtree", system-ui, sans-serif',
        '"Libre Baskerville", Georgia, serif',
    ),
    (
        "https://fonts.googleapis.com/css2?family=Rubik:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap",
        '"Rubik", system-ui, sans-serif',
        None,
    ),
)


def _pick_font_stack(site_identity: str) -> tuple[str, str, str | None]:
    h = int(hashlib.sha256(f"fonts|{site_identity}".encode("utf-8")).hexdigest(), 16)
    return _FONT_STACKS[h % len(_FONT_STACKS)]


_PROMO_DEFAULT_PROFESSIONAL: tuple[str, ...] = (
    "Book before Friday and we waive the scheduling fee on standard setups.",
    "New engagements this month include a structured onboarding workshop with your team leads.",
    "Annual agreements include priority scheduling and a named point of contact.",
    "Refer a partner organization: both sides receive a scoped discovery session.",
)

_PROMO_HOSPITALITY: tuple[str, ...] = (
    "Reserve before 5pm for Saturday dinner — we hold tables 15 minutes.",
    "Chef’s tasting menu: limited seats this month — book through Reservations.",
    "Complimentary dessert on parties of 6+ when you mention this banner at check-in.",
    "Weekday lunch prix fixe — see the host for today’s menu.",
)

_PROMO_FITNESS_WELLNESS: tuple[str, ...] = (
    "First class free for new members this month — sign in at the front desk.",
    "Bring a friend on Tuesdays: second guest pass included with your membership.",
    "Personal training intro pack: three sessions at a reduced rate through month end.",
)

_PROMO_NEWS: tuple[str, ...] = (
    "Corrections run at the top of a story with a timestamp when facts change materially.",
    "Tip the newsroom via Contact — say how to reach you and what you can document.",
    "Opinion and analysis are labeled separately from straight reporting.",
    "Weekend desk is intentionally light; urgent tips still route to the on-call editor.",
)
_PROMO_MARKETING: tuple[str, ...] = (
    "Discovery calls this season include analytics, Search Console, and realistic timelines.",
    "Retainer work ships with a changelog tied to rankings, CWV, and conversions — not vibes.",
    "We decline rush audits without data access; guesses aren’t billable.",
    "Pre-launch schema and monitoring checks are included in every go-live package we sign.",
)


def _promo_pool(vertical_id: str) -> tuple[str, ...]:
    v = (vertical_id or "").strip()
    if v == "news":
        return _PROMO_NEWS
    if v == "marketing_agency":
        return _PROMO_MARKETING
    if v in ("consulting", "legal", "accounting", "real_estate"):
        return _PROMO_MARKETING
    if v == "clothing":
        return (
            "WELCOME10: 10% off your first order (select items).",
            "Free tracked shipping over $75 — see cart for cutoff times.",
            "Returns accepted within 30 days in original condition — details in Returns policy.",
            "Drop restocks happen mid-week — join the newsletter for release notes.",
        )
    if v == "cafe_restaurant":
        return _PROMO_HOSPITALITY
    if v == "fitness":
        return _PROMO_FITNESS_WELLNESS
    if v in (
        "cleaning",
        "plumbing",
        "hvac",
        "roofing",
        "landscaping",
        "pest_control",
        "moving",
        "auto_repair",
        "electrical",
    ):
        return (
            "Same-week openings for recurring route clients — call dispatch for the next window.",
            "Emergency calls answered until 8pm on weekdays; after-hours rates apply.",
            "Winter readiness visits: ask about bundled inspections before peak season.",
            "Written estimates before we mobilize — no surprise line items on the first invoice.",
        )
    return _PROMO_DEFAULT_PROFESSIONAL


def _format_phone_real(site_identity: str, country_code: str, area: str | None) -> str:
    h = int(hashlib.sha256(f"tel|{site_identity}".encode("utf-8")).hexdigest(), 16)
    if country_code == "+1" and area:
        subscriber = 2000 + (h % 7998)
        exchange = 201 + ((h >> 12) % 798)
        if exchange >= 555:
            exchange += 4
        return f"+1 ({area}) {exchange:03d}-{subscriber:04d}"
    if country_code == "+65":
        return f"+65 {8100 + (h % 899)} {1000 + (h >> 8) % 8999}"
    if country_code == "+353":
        return f"+353 1 {400 + (h % 499)} {1000 + (h >> 6) % 8999}"
    if country_code == "+61":
        ac = 2 + (h % 7)
        return f"+61 {ac} {8000 + (h >> 4) % 1999} {1000 + (h >> 10) % 8999}"
    sub = 2000 + (h % 7998)
    ex = 201 + ((h >> 12) % 798)
    if ex >= 555:
        ex += 4
    return f"+1 (416) {ex:03d}-{sub:04d}"


def _founded_year(site_identity: str, current_year: int) -> int:
    h = int(hashlib.sha256(f"fy|{site_identity}".encode("utf-8")).hexdigest(), 16)
    span = max(2, min(14, current_year - 2010 - 2))
    return 2010 + (h % span)


def _review_count(site_identity: str) -> int:
    h = int(hashlib.sha256(f"rc|{site_identity}".encode("utf-8")).hexdigest(), 16)
    return 40 + (h % 160)


def _review_avg(site_identity: str) -> str:
    h = int(hashlib.sha256(f"ra|{site_identity}".encode("utf-8")).hexdigest(), 16)
    options = ["4.3", "4.4", "4.5", "4.6", "4.7", "4.8"]
    return options[h % len(options)]


def _cuisine_type(site_identity: str) -> str:
    h = int(hashlib.sha256(f"ct|{site_identity}".encode("utf-8")).hexdigest(), 16)
    cuisines = [
        "Contemporary", "Modern European", "Seasonal American",
        "Farm-to-table", "Mediterranean-inspired", "Pacific Northwest",
        "New American", "Modern Bistro", "Coastal Contemporary",
    ]
    return cuisines[h % len(cuisines)]


def _maps_embed_url(street: str, city: str, region: str, postal: str, country: str) -> str:
    parts = [street, city, region, postal, country]
    line = ", ".join(p for p in parts if p and p.strip())
    return f"https://maps.google.com/maps?q={quote_plus(line)}&hl=en&z=15&output=embed"

def _tz_abbrev(country: str, city: str, region: str) -> str:
    c = (country or "").strip().lower()
    ci = (city or "").strip().lower()
    r = (region or "").strip().lower()
    if "ireland" in c or ci == "dublin":
        return "GMT/IST"
    if "singapore" in c or ci == "singapore":
        return "SGT"
    if "australia" in c:
        if ci == "sydney" or r == "nsw":
            return "AET"
        if ci == "melbourne" or r == "vic":
            return "AET"
        return "AET"
    if "canada" in c:
        if ci == "vancouver" or r == "bc":
            return "PT"
        if ci == "calgary" or r == "ab":
            return "MT"
        if ci == "montreal" or r == "qc":
            return "ET"
        if ci == "toronto" or r == "on":
            return "ET"
        return "ET"
    return "GMT"

def _hours_for_vertical(vertical_id: str, rng: random.Random) -> dict[str, str]:
    vid = vertical_id.strip()
    if vid == "cafe_restaurant":
        opens = rng.choice(["11:00", "11:30", "12:00"])
        closes_wk = rng.choice(["22:00", "22:30", "23:00"])
        closes_fri = rng.choice(["23:00", "23:30", "00:00"])
        return {
            "hours_weekday": f"Mon–Thu {opens}–{closes_wk} · Fri {opens}–{closes_fri}",
            "hours_weekend": f"Sat 10:00–{closes_fri} · Sun 10:00–21:00",
            "hours_holiday": "Holiday hours: brunch 10:00–14:00; dinner from 16:00 — book ahead.",
        }
    if vid == "cleaning":
        open_t = rng.choice(["6:30", "7:00", "7:30", "8:00"])
        close_t = rng.choice(["17:00", "18:00", "19:00"])
        return {
            "hours_weekday": f"Mon–Fri {open_t}–{close_t} (dispatch)",
            "hours_weekend": rng.choice([
                "Sat 8:00–14:00 · emergency calls by arrangement",
                "Sat 8:00–12:00 · Sun closed",
                "Sat–Sun by appointment only",
            ]),
            "hours_holiday": "Public holidays: staffed on-call; scheduled routes move to the next business day.",
        }
    if vid == "fitness":
        open_t = rng.choice(["5:00", "5:30", "6:00"])
        close_t = rng.choice(["21:00", "22:00", "23:00"])
        return {
            "hours_weekday": f"Mon–Fri {open_t}–{close_t}",
            "hours_weekend": f"Sat–Sun {rng.choice(['7:00', '8:00'])}–{rng.choice(['18:00', '20:00'])}",
            "hours_holiday": "Holiday hours: 8:00–18:00 — check class cancellations online.",
        }
    if vid == "clothing":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['9:00', '10:00'])}–{rng.choice(['18:00', '19:00', '20:00'])}",
            "hours_weekend": f"Sat {rng.choice(['10:00', '9:00'])}–{rng.choice(['17:00', '18:00'])} · Sun {rng.choice(['11:00–17:00', 'closed'])}",
            "hours_holiday": "Holiday hours posted two weeks before each long weekend.",
        }
    if vid == "news":
        return {
            "hours_weekday": "Newsroom Mon–Fri 9:00–18:00",
            "hours_weekend": "Weekend: on-call editor for breaking tips",
            "hours_holiday": "Holiday desk: reduced staff; corrections still monitored.",
        }
    if vid == "marketing_agency":
        tz = "TZ"
        return {
            "hours_weekday": f"Mon–Fri 9:00–18:00 ({tz})",
            "hours_weekend": "Sat by appointment · Sun closed",
            "hours_holiday": "Holiday cover: account leads check inboxes twice daily.",
        }
    if vid == "dental":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['8:00', '8:30', '9:00'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": rng.choice(["Sat 9:00–14:00 · Sun closed", "Sat–Sun closed"]),
            "hours_holiday": "Closed on public holidays; emergency line available.",
        }
    if vid == "medical":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['8:00', '8:30'])}–{rng.choice(['17:00', '17:30', '18:00'])}",
            "hours_weekend": rng.choice(["Sat 9:00–13:00 · Sun closed", "Sat–Sun closed"]),
            "hours_holiday": "Emergency referrals available; clinic closed on public holidays.",
        }
    if vid in ("plumbing", "electrical", "hvac"):
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:00', '7:30', '8:00'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": rng.choice([
                "Sat 8:00–14:00 · Sun emergency only",
                "Sat–Sun emergency calls 24/7",
                "Sat 8:00–12:00 · Sun closed",
            ]),
            "hours_holiday": "24/7 emergency service available; regular scheduling resumes next business day.",
        }
    if vid == "roofing":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:00', '7:30'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": "Sat 8:00–13:00 · Sun closed (weather permitting)",
            "hours_holiday": "Seasonal; emergency tarping available year-round.",
        }
    if vid == "landscaping":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:00', '7:30', '8:00'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": f"Sat {rng.choice(['8:00–14:00', '8:00–12:00'])} · Sun closed",
            "hours_holiday": "Seasonal service March–November; snow removal available year-round.",
        }
    if vid == "legal":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['8:30', '9:00'])}–{rng.choice(['17:00', '17:30', '18:00'])}",
            "hours_weekend": "By appointment only",
            "hours_holiday": "Closed on public holidays; urgent matters by prior arrangement.",
        }
    if vid == "auto_repair":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:30', '8:00'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": f"Sat {rng.choice(['8:00–14:00', '8:00–16:00'])} · Sun closed",
            "hours_holiday": "Closed on public holidays; drop-off available.",
        }
    if vid == "moving":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:00', '8:00'])}–{rng.choice(['18:00', '19:00'])}",
            "hours_weekend": "Sat–Sun 8:00–17:00 (by booking)",
            "hours_holiday": "Available on most holidays with advance booking.",
        }
    if vid == "real_estate":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['9:00', '9:30'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": "Sat–Sun by appointment for showings",
            "hours_holiday": "Open houses scheduled seasonally; virtual tours available 24/7.",
        }
    if vid == "pest_control":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['7:00', '8:00'])}–{rng.choice(['17:00', '18:00'])}",
            "hours_weekend": rng.choice(["Sat 8:00–13:00 · Sun closed", "Sat–Sun emergency only"]),
            "hours_holiday": "Emergency service available 24/7 for active infestations.",
        }
    if vid == "accounting":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['8:30', '9:00'])}–{rng.choice(['17:00', '17:30'])}",
            "hours_weekend": rng.choice(["Closed", "Tax season: Sat 9:00–14:00"]),
            "hours_holiday": "Extended hours Jan–Apr for tax season.",
        }
    if vid == "consulting":
        return {
            "hours_weekday": f"Mon–Fri {rng.choice(['9:00', '8:30'])}–{rng.choice(['17:30', '18:00'])}",
            "hours_weekend": "By appointment",
            "hours_holiday": "Reduced availability; email monitored.",
        }
    return {
        "hours_weekday": f"Mon–Fri {rng.choice(['8:00', '8:30', '9:00'])}–{rng.choice(['17:00', '17:30', '18:00'])}",
        "hours_weekend": rng.choice(["Sat 10:00–14:00 · Sun closed", "Sat–Sun closed", "Sat 9:00–13:00 · Sun closed"]),
        "hours_holiday": "Holiday hours: email-only with next-business-day callbacks.",
    }


def _normalize_custom_domain(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"^https?://", "", s)
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0]
    s = s.split("#", 1)[0]
    s = s.strip().strip(".")
    # Allow punycode and dots/hyphens; drop spaces and other junk.
    s = re.sub(r"[^a-z0-9.-]+", "", s)
    # collapse consecutive dots
    s = re.sub(r"\.+", ".", s)
    if not s or "." not in s:
        return ""
    if len(s) > 253:
        s = s[:253]
    return s

def generate_brand(
    rng: random.Random,
    brand_cfg: dict[str, Any] | None = None,
    vertical: dict[str, Any] | None = None,
    theme_pack: dict[str, Any] | None = None,
    site_identity: str | None = None,
) -> dict[str, Any]:
    vid = str((vertical or {}).get("id") or "")
    pre = theme_pack.get("brand_prefixes") if isinstance(theme_pack, dict) else None
    suf = theme_pack.get("brand_suffixes") if isinstance(theme_pack, dict) else None
    ident_pre = (site_identity or "").strip() or str(rng.random())
    # Peek at address city for district-based naming (we need city before full address pick)
    pre_addr = pick_address_for_site(ident_pre)
    pre_city = pre_addr[1]
    name = _generate_brand_name(rng, vid, pre_city, ident_pre, pre, suf)
    year = datetime.date.today().year

    tagline = f"{name} — clarity, growth, and measurable outcomes."
    if vertical:
        pool = vertical.get("tagline_candidates")
        if isinstance(pool, list) and pool:
            tagline = _coerce_vertical_text(rng.choice(pool)).format(brand_name=name)

    domain_mode = str((brand_cfg or {}).get("domain_mode") or "none")
    tlds_raw = (brand_cfg or {}).get("tlds")
    tlds = [str(x) for x in tlds_raw] if isinstance(tlds_raw, list) else None
    custom_domain = _normalize_custom_domain(str((brand_cfg or {}).get("custom_domain") or ""))

    if domain_mode == "custom" and custom_domain:
        domain = custom_domain
        email = f"contact@{domain}"
    elif domain_mode == "brand_tld":
        domain = f"{_slug_domain(name)}.{_pick_tld(rng, tlds)}"
        email = f"contact@{domain}"
    elif domain_mode == "random_tld":
        domain = f"{_random_local_part(rng)}.{_pick_tld(rng, tlds)}"
        email = f"contact@{domain}"
    else:
        # Match mailbox host to brand slug (reads like a real business domain, not random gibberish).
        slug = _slug_domain(name) or "site"
        domain = f"{slug}.{_pick_tld(rng, tlds)}"
        email = f"contact@{domain}"
    ident = (site_identity or "").strip() or f"{name}|{domain}|{rng.random()}"
    # Address: catalog = real street names per city + synthetic postals; hybrid = optional validator;
    # address_mode "fictional"/"fake" in brand_cfg.address hides street from structured data (legacy).
    addr_cfg = (brand_cfg or {}).get("address") if isinstance(brand_cfg, dict) else {}
    addr_explicit = str((addr_cfg or {}).get("address_mode") or "").strip().lower() if isinstance(addr_cfg, dict) else ""
    if isinstance(addr_cfg, dict) and addr_cfg.get("validation_mode") == "hybrid":
        addr_mode = "hybrid"
    elif addr_explicit in {"fictional", "fake"}:
        addr_mode = "fictional"
    else:
        addr_mode = "catalog"
    addr_display = str((addr_cfg or {}).get("display") or "full").strip().lower()

    def _validator(payload: dict[str, Any]) -> dict[str, Any]:
        # Hook for external validation; if not configured, just echo.
        # A real implementation can be wired via dependency injection without changing this module.
        validate_cb = (addr_cfg or {}).get("validator")
        if callable(validate_cb):
            return validate_cb(payload)
        return payload

    if addr_mode == "hybrid":
        street, city, region, postal, country, cc, area = pick_address_for_site(
            ident,
            mode="hybrid",
            validator=_validator,
        )
    else:
        street, city, region, postal, country, cc, area = pick_address_for_site(ident)
    # Basic format validations (keeps outputs looking real per country)
    ctry = str(country or "").strip()
    if ctry == "Canada" and postal and not _RE_CAN_POSTAL.match(str(postal).strip().upper()):
        # If a bad code sneaks in, blank it rather than shipping a nonsense format.
        postal = ""
    if ctry == "Ireland" and postal and not _RE_IE_EIRCODE.match(str(postal).strip().upper()):
        postal = ""
    # Use full line by default; `address.display: city_only` strips street/postal (non-hybrid).
    if addr_display == "city_only" and addr_mode != "hybrid":
        street = ""
        if ctry in {"Ireland", "Canada"}:
            postal = ""
    phone = _format_phone_real(ident, cc, area)
    if region:
        city_region_postal = f"{city}, {region} {postal}".strip()
    else:
        city_region_postal = f"{city} {postal}".strip()
    street_clean = street.strip()
    if street_clean:
        address_multiline = f"{street_clean}\n{city_region_postal}\n{country}"
        address_one_line = f"{street_clean}, {city_region_postal}, {country}"
        maps_line = ", ".join(p for p in [street_clean, city, region, postal, country] if p and str(p).strip())
        maps_embed_url = _maps_embed_url(street_clean, city, region, postal, country)
        maps_search_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(maps_line)}"
    else:
        address_multiline = f"{city_region_postal}\n{country}".strip()
        address_one_line = f"{city_region_postal}, {country}".strip(" ,")
        maps_line = ", ".join(p for p in [city, region, country] if p and str(p).strip())
        maps_embed_url = _maps_embed_url(city, city, region, "", country)
        maps_search_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(maps_line)}"
    # contact_block (strict_components) requires non-empty address_line1; city_only mode may clear street.
    address_line1 = street_clean if street_clean else (
        f"{city} — office & dispatch" if city else "Main office"
    )
    vid = str((vertical or {}).get("id") or "")
    if vid == "news":
        email = f"newsroom@{domain}"
    tz = _tz_abbrev(country, city, region)
    hours = _hours_for_vertical(vid, rng)
    # Apply deterministic tz where it matters.
    if vid == "marketing_agency":
        hours["hours_weekday"] = f"Mon–Fri 9:00–18:00 ({tz})"
    founded_year = _founded_year(ident, year)
    promo_h = int(hashlib.sha256(f"promo|{ident}".encode("utf-8")).hexdigest(), 16)
    _promos = _promo_pool(vid)
    if vid == "news":
        promo_banner_text = ""
    else:
        promo_banner_text = _promos[promo_h % len(_promos)]
    gfont_url, body_ff, head_ff = _pick_font_stack(ident)
    handle = ((_slug_domain(name) or "brand")[:22]).strip("-") or "brand"
    soc_tw = soc_li = soc_fb = soc_ig = soc_tt = ""
    if vid == "news":
        soc_tw = f"https://twitter.com/{handle}"
        soc_li = f"https://www.linkedin.com/company/{handle}"
        soc_fb = f"https://www.facebook.com/{handle}"
    elif vid == "clothing":
        soc_ig = f"https://www.instagram.com/{handle}"
        soc_tt = f"https://www.tiktok.com/@{handle}"
        soc_fb = f"https://www.facebook.com/{handle}"
    elif vid in ("marketing_agency", "consulting", "legal", "accounting", "real_estate"):
        soc_li = f"https://www.linkedin.com/company/{handle}"
        soc_fb = f"https://www.facebook.com/{handle}"
        if rng.random() < 0.4:
            soc_tw = f"https://twitter.com/{handle}"
    elif vid in ("cafe_restaurant", "fitness", "landscaping", "dental", "medical"):
        soc_ig = f"https://www.instagram.com/{handle}"
        soc_fb = f"https://www.facebook.com/{handle}"
    elif rng.random() < 0.5:
        soc_fb = f"https://www.facebook.com/{handle}"
        if rng.random() < 0.3:
            soc_ig = f"https://www.instagram.com/{handle}"

    # Business parameters
    team_lo, team_hi = _VERTICAL_TEAM_RANGE.get(vid, (4, 15))
    team_size = rng.randint(team_lo, team_hi)
    client_type = _VERTICAL_CLIENT_TYPE.get(vid, "B2C")
    price_pool = _VERTICAL_PRICE_RANGE.get(vid, ("Varies",))
    price_range = localize_money_labels(rng.choice(price_pool), country)
    service_area_zones = pick_districts_for_site(ident, city, rng.randint(5, 12), brand_name=name)
    zones_preview = ", ".join(service_area_zones[:10])
    if len(service_area_zones) > 10:
        zones_preview += ", and nearby areas"
    contact_districts_line = f"Neighborhoods we serve regularly: {zones_preview}." if service_area_zones else ""
    geo_coords = pick_geo_for_city(city)
    lic_pool = _VERTICAL_LICENSES.get(vid, ())
    licenses = list(rng.sample(lic_pool, min(rng.randint(1, 3), len(lic_pool)))) if lic_pool else []
    cert_pool = _VERTICAL_CERTIFICATIONS.get(vid, ())
    certifications = list(rng.sample(cert_pool, min(rng.randint(0, 2), len(cert_pool)))) if cert_pool else []

    phone_fmt_h = int(hashlib.sha256(f"phonefmt|{ident}".encode("utf-8")).hexdigest(), 16)
    phone_secondary = ""
    if rng.random() < 0.3:
        phone_secondary = _format_phone_real(ident + "_fax", cc, area)

    extra_emails: list[dict[str, str]] = []
    if rng.random() < 0.4:
        dept_pool = ["billing", "support", "info", "hello", "office", "admin", "hr", "careers"]
        dept = rng.choice(dept_pool)
        extra_emails.append({"label": dept.title(), "email": f"{dept}@{domain}"})

    suite_number = ""
    if rng.random() < 0.35 and street_clean:
        suite_number = f"Suite {rng.randint(100, 999)}"

    brand_out = {
        "generation_identity": ident,
        "brand_name": name,
        "tagline": tagline,
        "email": email,
        "phone": phone,
        "phone_secondary": phone_secondary,
        "extra_emails": extra_emails,
        "address_mode": addr_mode,
        "service_area": city,
        "service_area_zones": service_area_zones,
        "contact_districts_line": contact_districts_line,
        "address": address_one_line,
        "address_multiline": address_multiline,
        "address_line1": address_line1,
        "suite_number": suite_number,
        "city": city,
        "region": region,
        "postal_code": postal,
        "country": country,
        "city_region_postal": city_region_postal,
        "maps_embed_url": maps_embed_url,
        "maps_search_url": maps_search_url,
        "geo_lat": geo_coords[0] if geo_coords else None,
        "geo_lng": geo_coords[1] if geo_coords else None,
        "founded_year": founded_year,
        "team_size": team_size,
        "client_type": client_type,
        "price_range": price_range,
        "licenses": licenses,
        "certifications": certifications,
        "insurance": "Fully insured" if rng.random() < 0.7 else "Bonded & insured",
        "promo_banner_text": promo_banner_text,
        "social_facebook": soc_fb,
        "social_instagram": soc_ig,
        "social_tiktok": soc_tt,
        "social_twitter": soc_tw,
        "social_linkedin": soc_li,
        "review_count": _review_count(ident),
        "review_avg": _review_avg(ident),
        "cuisine_type": _cuisine_type(ident) if vid == "cafe_restaurant" else "",
        **hours,
        "timezone_abbrev": tz,
        "year": year,
        "domain": domain,
        "locale": "en",
        "google_fonts_stylesheet_url": gfont_url,
        "body_font_family": body_ff,
        "heading_font_family": head_ff or body_ff,
    }
    return merge_geo_into_brand(brand_out, brand_cfg)
