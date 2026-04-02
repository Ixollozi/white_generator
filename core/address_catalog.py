from __future__ import annotations

import hashlib
import random
from typing import Any, Literal

# Real major thoroughfares per metro (deterministic pick by site hash).
# Building numbers may not match a real doorway; postal codes are syntactically valid but not
# verified to that segment — use brand_cfg.address.validation_mode == "hybrid" + validator for exact data.
_CITY_STREETS: dict[str, tuple[str, ...]] = {
    "Toronto": (
        "Queen St W",
        "King St W",
        "Spadina Ave",
        "Bloor St W",
        "Yonge St",
        "Bay St",
        "College St",
        "Dundas St W",
        "University Ave",
        "Front St W",
        "Adelaide St W",
        "Richmond St W",
        "Bathurst St",
        "Parliament St",
        "Jarvis St",
        "Ossington Ave",
        "Dufferin St",
        "St Clair Ave W",
        "Eglinton Ave W",
        "Finch Ave W",
    ),
    "Vancouver": (
        "Granville St",
        "Burrard St",
        "Davie St",
        "Cambie St",
        "Main St",
        "Hornby St",
        "Robson St",
        "W Pender St",
        "W Hastings St",
        "Commercial Dr",
    ),
    "Calgary": (
        "Stephen Ave SW",
        "17 Ave SW",
        "Macleod Tr S",
        "9 Ave SW",
        "4 St SW",
        "Centre St S",
        "14 St SW",
        "Memorial Dr NW",
    ),
    "Montreal": ("Rue Sainte-Catherine O", "Boul Saint-Laurent", "Rue Peel", "Rue Notre-Dame O"),
    "Singapore": (
        "Orchard Rd",
        "Bras Basah Rd",
        "Raffles Quay",
        "Beach Rd",
        "Circular Rd",
        "North Bridge Rd",
        "South Bridge Rd",
        "New Bridge Rd",
    ),
    "Dublin": ("Pearse St", "Capel St", "George St", "South Lotts Rd", "Thomas St"),
    "Sydney": ("George St", "Pitt St", "Liverpool St", "Kent St", "York St"),
    "Melbourne": ("Collins St", "Bourke St", "Flinders St", "Swanston St", "Elizabeth St"),
}
_STREETS_FALLBACK: tuple[str, ...] = ("Main St", "High St", "Centre Ave", "Market St")

# Streets where a 100–900 block would look wrong; pick a tighter range from the row index.
_STREET_NUMBER_RANGES: dict[str, tuple[int, int]] = {
    "Circular Rd": (1, 60),
    "Stephen Ave SW": (100, 299),
    "Raffles Quay": (1, 45),
}

DISTRICTS: dict[str, tuple[str, ...]] = {
    "Toronto": (
        "North York", "Scarborough", "Etobicoke", "Mississauga", "Markham",
        "Richmond Hill", "Vaughan", "Brampton", "Oakville", "Pickering",
        "East York", "The Beaches", "Leslieville", "Liberty Village", "Yorkville",
    ),
    "Vancouver": (
        # Superset for non-stratified callers; primary Vancouver picks use bucketed sampling.
        "Burnaby", "Surrey", "Richmond", "North Vancouver", "West Vancouver",
        "Coquitlam", "New Westminster", "Langley", "Kitsilano", "Mount Pleasant",
        "Gastown", "Yaletown", "Kerrisdale", "Dunbar", "Commercial Drive",
        "Metrotown", "Lougheed", "Brentwood", "Steveston", "Fleetwood",
        "Lonsdale", "Lynn Valley", "Deep Cove", "Whalley", "Cloverdale",
        "Delta", "Tsawwassen", "White Rock", "Port Moody", "Port Coquitlam",
        "Maple Ridge", "Pitt Meadows", "Marpole", "Fairview", "Shaughnessy",
        "West End", "Coal Harbour", "Renfrew-Collingwood", "Hastings-Sunrise",
    ),
    "Calgary": (
        "Beltline", "Kensington", "Inglewood", "Bridgeland", "Mission",
        "Marda Loop", "Airdrie", "Cochrane", "Okotoks", "Chestermere",
        "Brentwood", "Bowness", "Varsity", "Bankview", "Altadore",
    ),
    "Montreal": (
        "Plateau Mont-Royal", "Griffintown", "Verdun", "Westmount", "Outremont",
        "Mile End", "Laval", "Longueuil", "Saint-Laurent", "Rosemont",
        "Villeray", "Hochelaga", "Old Montreal", "Pointe-Saint-Charles", "NDG",
    ),
    "Singapore": (
        "Orchard", "Marina Bay", "Bugis", "Tanjong Pagar", "Tiong Bahru",
        "Holland Village", "Dempsey Hill", "Chinatown", "Little India", "Kampong Glam",
        "Jurong East", "Woodlands", "Tampines", "Bedok", "Clementi",
    ),
    "Dublin": (
        "Rathmines",
        "Ranelagh",
        "Drumcondra",
        "Ballsbridge",
        "Clontarf",
        "Sandymount",
        "Ringsend",
        "Phibsborough",
        "Blackrock",
        "Dun Laoghaire",
        "Tallaght",
        "Swords",
        "Howth",
        "Glasnevin",
        "Donnybrook",
        "Lucan",
        "Blanchardstown",
        "Clondalkin",
        "Cherrywood",
        "Cabra",
        "Crumlin",
        "Drimnagh",
        "Finglas",
        "Kilbarrack",
        "Malahide",
        "Portmarnock",
        "Stillorgan",
        "Terenure",
        "Walkinstown",
        "Castleknock",
        "Dalkey",
        "Foxrock",
        "Harold's Cross",
        "Inchicore",
        "Killester",
        "Raheny",
        "Stepaside",
    ),
    "Sydney": (
        "Surry Hills", "Newtown", "Bondi", "Manly", "Parramatta",
        "Chatswood", "Mosman", "Darlinghurst", "Glebe", "Paddington",
        "Balmain", "Marrickville", "Coogee", "Randwick", "Ryde",
    ),
    "Melbourne": (
        "Fitzroy", "South Yarra", "Carlton", "Richmond", "St Kilda",
        "Brunswick", "Collingwood", "Prahran", "Footscray", "Docklands",
        "Southbank", "Hawthorn", "Toorak", "Caulfield", "Box Hill",
    ),
}

CITY_GEO: dict[str, tuple[float, float]] = {
    "Toronto": (43.6532, -79.3832),
    "Vancouver": (49.2827, -123.1207),
    "Calgary": (51.0447, -114.0719),
    "Montreal": (45.5017, -73.5673),
    "Singapore": (1.3521, 103.8198),
    "Dublin": (53.3498, -6.2603),
    "Sydney": (-33.8688, 151.2093),
    "Melbourne": (-37.8136, 144.9631),
}

SURNAMES: tuple[str, ...] = (
    "Mitchell", "Garcia", "Henderson", "Clarke", "Sullivan", "Patel", "Kim",
    "Thompson", "Martinez", "Anderson", "Wilson", "Taylor", "Campbell", "Roberts",
    "Stewart", "Phillips", "Morris", "Nguyen", "Walker", "Baker", "Cooper",
    "Reed", "Bell", "Ward", "Hughes", "Foster", "Barnes", "Ross", "Perry",
    "Graham", "Shaw", "Grant", "Murray", "Stone", "Crawford", "Harper",
    "Chambers", "Webb", "Burke", "Walsh", "Flynn", "Quinn", "Dunn", "Reid",
    "Doyle", "Lynch", "Brennan", "Brady", "Fong", "Chan", "Lim", "Tan",
    "Chong", "O'Brien", "Murphy", "Kelly", "Ryan", "Byrne", "Carroll",
)


_VANCOUVER_DISTRICT_BUCKETS: tuple[tuple[str, ...], ...] = (
    ("Gastown", "Yaletown", "Coal Harbour", "West End", "Downtown Eastside"),
    ("Kitsilano", "Point Grey", "Dunbar", "Kerrisdale", "Fairview", "Shaughnessy"),
    ("Mount Pleasant", "Riley Park", "Commercial Drive", "Hastings-Sunrise", "Renfrew-Collingwood"),
    ("Marpole", "Oakridge", "Sunset", "Killarney", "Victoria-Fraserview"),
    ("Burnaby Heights", "Metrotown", "Brentwood", "Lougheed", "Edmonds"),
    ("North Vancouver", "Lonsdale", "Lynn Valley", "Deep Cove", "West Vancouver"),
    ("Richmond", "Steveston", "Brighouse", "Aberdeen"),
    ("New Westminster", "Queensborough", "Uptown"),
    ("Coquitlam", "Port Moody", "Port Coquitlam", "Burquitlam"),
    ("Surrey", "Whalley", "Cloverdale", "Fleetwood", "Newton", "South Surrey"),
    ("Delta", "Tsawwassen", "Ladner", "White Rock", "Langley City", "Fort Langley"),
    ("Maple Ridge", "Pitt Meadows", "Mission"),
)


def _pick_vancouver_districts_stratified(site_identity: str, brand_name: str, n_want: int) -> list[str]:
    """Round-robin across metro buckets so two sites rarely share the same all-7 subset."""
    h = int(
        hashlib.sha256(
            f"districts|{site_identity}|Vancouver|{(brand_name or '').strip()}".encode("utf-8"),
        ).hexdigest(),
        16,
    )
    rng = random.Random(h)
    buckets = [list(b) for b in _VANCOUVER_DISTRICT_BUCKETS]
    order = list(range(len(buckets)))
    rng.shuffle(order)
    for b in buckets:
        rng.shuffle(b)
    picked: list[str] = []
    rnd = 0
    guard = 0
    while len(picked) < n_want and guard < 200:
        guard += 1
        progressed = False
        for bi in order:
            if len(picked) >= n_want:
                break
            bucket = buckets[bi]
            if rnd < len(bucket):
                c = bucket[rnd]
                if c not in picked:
                    picked.append(c)
                progressed = True
        if not progressed:
            break
        rnd += 1
    return picked[:n_want]


def pick_districts_for_site(
    site_identity: str,
    city: str,
    count: int = 5,
    *,
    brand_name: str = "",
) -> list[str]:
    n_want = min(max(1, count), 12)
    if city == "Vancouver":
        return _pick_vancouver_districts_stratified(site_identity, brand_name, n_want)
    pool = list(DISTRICTS.get(city, ()))
    if not pool:
        return []
    h = int(
        hashlib.sha256(
            f"districts|{site_identity}|{city}|{(brand_name or '').strip()}".encode("utf-8"),
        ).hexdigest(),
        16,
    )
    rng = random.Random(h)
    rng.shuffle(pool)
    n = min(n_want, len(pool))
    return pool[:n]


def pick_geo_for_city(city: str) -> tuple[float, float] | None:
    return CITY_GEO.get(city)


def pick_surname(site_identity: str) -> str:
    h = int(hashlib.sha256(f"surname|{site_identity}".encode("utf-8")).hexdigest(), 16)
    return SURNAMES[h % len(SURNAMES)]


def _can_postal(i: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    return f"M{1 + (i % 8)}{letters[i % n]} {1 + (i % 9)}{letters[(i * 5) % n]}{1 + (i % 9)}"


def _can_postal_van(i: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    return f"V{6 + (i % 3)}{letters[i % n]} {1 + (i % 9)}{letters[(i * 7) % n]}{1 + (i % 9)}"


def _vancouver_fsa_prefixes(street: str) -> tuple[str, ...]:
    """
    Greater Vancouver (GVA) FSAs only — never V8* (Vancouver Island / Victoria area).
    Downtown-ish streets get V6B/V6C/V6E/V6G; other catalog streets get common Metro Vancouver FSAs.
    """
    s = (street or "").upper()
    if any(
        x in s
        for x in (
            "GRANVILLE",
            "BURRARD",
            "HORNBY",
            "ROBSON",
            "W PENDER",
            "W HASTINGS",
            "DAVIE",
        )
    ):
        return ("V6B", "V6C", "V6E", "V6G")
    if "CAMBIE" in s or "MAIN ST" in s or s.endswith(" MAIN ST"):
        return ("V5Z", "V6H", "V6P", "V6R")
    if "COMMERCIAL" in s:
        return ("V5L", "V5N", "V5K")
    # Default: Metro Vancouver ring (still not V8*)
    return ("V5K", "V5M", "V5R", "V6J", "V6K", "V6L", "V6M", "V6N", "V6P", "V6R", "V6S", "V6T", "V6Z")


def _vancouver_postal_for_street(street: str, salt: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    opts = _vancouver_fsa_prefixes(street)
    fsa = opts[salt % len(opts)]
    ld1 = 1 + (salt % 9)
    ch = letters[(salt * 11) % n]
    ld2 = 1 + ((salt * 7) % 9)
    return f"{fsa} {ld1}{ch}{ld2}"


def _can_postal_ca(i: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    # Alberta: keep within Calgary-like FSAs (T2*, T3*) to avoid obvious city/postal mismatch.
    fsa_digit = 2 if (i % 2 == 0) else 3
    return f"T{fsa_digit}{letters[i % n]} {1 + (i % 9)}{letters[(i * 11) % n]}{1 + (i % 9)}"


def _calgary_fsa_prefixes(street: str) -> tuple[str, ...]:
    """
    Pick Forward Sortation Area (first 3 chars of postal) consistent with street quadrant.
    SW avenues (e.g. 17 Ave SW) should not get NW FSAs like T2N (University).
    """
    s = (street or "").upper()
    if " NW" in s or s.endswith(" NW"):
        return ("T2N", "T3B", "T3L")
    if " NE" in s or s.endswith(" NE"):
        return ("T2A", "T2C", "T2E")
    if " SE" in s or s.endswith(" SE"):
        return ("T2G", "T2H", "T2J")
    if " SW" in s or " AVE SW" in s or " ST SW" in s or " STEPHEN AVE" in s:
        return ("T2S", "T2T", "T2R")
    if "MACLEOD" in s or " TR S" in s or " TRAIL S" in s:
        return ("T2G", "T2H", "T2J")
    if "CENTRE ST" in s:
        return ("T2P", "T2R", "T2S")
    return ("T2P", "T2S", "T2T")


def _calgary_postal_for_street(street: str, salt: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    opts = _calgary_fsa_prefixes(street)
    fsa = opts[salt % len(opts)]
    ld1 = 1 + (salt % 9)
    ch = letters[(salt * 11) % n]
    ld2 = 1 + ((salt * 7) % 9)
    return f"{fsa} {ld1}{ch}{ld2}"


def _can_postal_qc(i: int) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    n = len(letters)
    return f"H{2 + (i % 4)}{letters[i % n]} {1 + (i % 9)}{letters[(i * 13) % n]}{1 + (i % 9)}"


def _sg_postal(i: int) -> str:
    return f"{18900 + (i * 17) % 1200:06d}"


def _ie_postal(i: int) -> str:
    # Ireland Eircode (Dublin routing keys) example: D01 X2X2 (4 chars after space).
    routing = 1 + (i % 24)
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"  # omit easily confused letters
    n = len(letters)
    a = letters[i % n]
    b = str((i * 7) % 10)
    c = letters[(i * 11) % n]
    d = str((i * 13) % 10)
    return f"D{routing:02d} {a}{b}{c}{d}"


def _au_postal(i: int) -> str:
    return f"{2000 + (i * 19) % 200}"


def _au_postal_mel(i: int) -> str:
    return f"{3000 + (i * 23) % 500}"


_BASE_META: tuple[tuple[str, str, str, str, str | None, type], ...] = (
    ("Toronto", "ON", "Canada", "+1", "416", _can_postal),
    ("Toronto", "ON", "Canada", "+1", "647", _can_postal),
    ("Vancouver", "BC", "Canada", "+1", "604", _can_postal_van),
    ("Vancouver", "BC", "Canada", "+1", "236", _can_postal_van),
    ("Calgary", "AB", "Canada", "+1", "403", _can_postal_ca),
    ("Montreal", "QC", "Canada", "+1", "514", _can_postal_qc),
    ("Singapore", "", "Singapore", "+65", None, _sg_postal),
    ("Dublin", "Dublin", "Ireland", "+353", "1", _ie_postal),
    ("Sydney", "NSW", "Australia", "+61", "2", _au_postal),
    ("Melbourne", "VIC", "Australia", "+61", "3", _au_postal_mel),
)

def _build_rows() -> list[tuple[str, str, str, str, str, str, str | None, int]]:
    rows: list[tuple[str, str, str, str, str, str, str | None, int]] = []
    idx = 0
    for city, region, country, cc, area, postal_fn in _BASE_META:
        streets = _CITY_STREETS.get(city, _STREETS_FALLBACK)
        for snum in range(108, 988, 7):
            street = streets[idx % len(streets)]
            idx += 1
            if city == "Calgary" and country == "Canada":
                postal = _calgary_postal_for_street(street, idx)
            elif city == "Vancouver" and country == "Canada":
                postal = _vancouver_postal_for_street(street, idx)
            else:
                postal = postal_fn(idx)
            sr = _STREET_NUMBER_RANGES.get(street)
            if sr is not None:
                lo, hi = sr
                snum_eff = lo + (idx % max(1, (hi - lo + 1)))
                line1 = f"{snum_eff} {street}"
            elif str(country) == "Singapore":
                lo, hi = (1, 120)
                snum_eff = lo + (idx % max(1, (hi - lo + 1)))
                line1 = f"{snum_eff} {street}"
            else:
                line1 = f"{snum} {street}"
            rows.append((line1, city, region, postal, country, cc, area, idx))
    return rows


ADDRESS_ROWS = _build_rows()


def _catalog_address_for_site(site_identity: str) -> tuple[str, str, str, str, str, str, str | None]:
    """Deterministic address: real street names from the catalog + synthetic postal (format-valid)."""
    h = int(hashlib.sha256(site_identity.encode("utf-8")).hexdigest(), 16)
    i = h % len(ADDRESS_ROWS)
    line1, city, region, postal, country, cc, area, _ = ADDRESS_ROWS[i]
    return line1, city, region, postal, country, cc, area


def pick_address_for_site(
    site_identity: str,
    *,
    mode: Literal["catalog", "hybrid"] = "catalog",
    validator: Any | None = None,
) -> tuple[str, str, str, str, str, str, str | None]:
    """
    Select address for a site.

    - catalog: real major streets per city; postal codes match country format but are not geovalidated.
    - hybrid: if a `validator` callable is provided, it may adjust or reject the pick;
      otherwise same as catalog.
    """
    line1, city, region, postal, country, cc, area = _catalog_address_for_site(site_identity)
    if mode != "hybrid" or validator is None:
        return line1, city, region, postal, country, cc, area
    try:
        validated = validator(
            {
                "line1": line1,
                "city": city,
                "region": region,
                "postal": postal,
                "country": country,
                "country_code": cc,
                "area": area,
                "site_identity": site_identity,
            }
        )
    except Exception:
        return line1, city, region, postal, country, cc, area
    if not isinstance(validated, dict):
        return line1, city, region, postal, country, cc, area
    return (
        str(validated.get("line1") or line1),
        str(validated.get("city") or city),
        str(validated.get("region") or region),
        str(validated.get("postal") or postal),
        str(validated.get("country") or country),
        str(validated.get("country_code") or cc),
        validated.get("area") or area,
    )
