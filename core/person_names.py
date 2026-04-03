"""Deterministic, site-unique personal names (reduces cross-site fingerprinting)."""

from __future__ import annotations

import hashlib
from typing import Any

# ---------------------------------------------------------------------------
# Large pools — North American / UK / IE professional register (no sci-fi).
# ---------------------------------------------------------------------------
_FIRST_GENERAL: tuple[str, ...] = (
    "James", "Michael", "Robert", "David", "William", "Richard", "Joseph", "Thomas",
    "Christopher", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul",
    "Andrew", "Joshua", "Kenneth", "Kevin", "Brian", "George", "Timothy", "Ronald",
    "Jason", "Edward", "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric", "Stephen",
    "Jonathan", "Larry", "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Gregory",
    "Frank", "Raymond", "Alexander", "Patrick", "Jack", "Dennis", "Jerry", "Tyler",
    "Aaron", "Henry", "Adam", "Douglas", "Nathan", "Peter", "Zachary", "Kyle", "Walter",
    "Harold", "Carl", "Keith", "Roger", "Jeremy", "Ethan", "Christian", "Sean", "Gerald",
    "Austin", "Arthur", "Lawrence", "Jesse", "Dylan", "Bryan", "Joe", "Billy", "Bruce",
    "Ralph", "Roy", "Louis", "Philip", "Bobby", "Johnny", "Albert", "Willie", "Wayne",
    "Alan", "Juan", "Eugene", "Russell", "Randy", "Vincent", "Brent", "Wesley",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica",
    "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra", "Ashley", "Kimberly",
    "Emily", "Donna", "Michelle", "Carol", "Amanda", "Melissa", "Deborah", "Stephanie",
    "Rebecca", "Laura", "Sharon", "Cynthia", "Kathleen", "Amy", "Angela", "Shirley",
    "Anna", "Brenda", "Pamela", "Nicole", "Ruth", "Katherine", "Samantha", "Christine",
    "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper",
    "Evelyn", "Abigail", "Sofia", "Madison", "Grace", "Chloe", "Victoria", "Lily", "Natalie",
    "Zoe", "Hannah", "Layla", "Penelope", "Riley", "Zoey", "Nora", "Lillian", "Eleanor",
    "Stella", "Violet", "Skylar", "Bella", "Claire", "Lucy", "Paisley", "Everly", "Anna",
    "Caroline", "Naomi", "Ariana", "Allison", "Sarah", "Maya", "Willow", "Kennedy", "Kinsley",
    "Valerie", "Diane", "Julie", "Joyce", "Heather", "Teresa", "Gloria", "Janet", "Catherine",
    "Frances", "Ann", "Martha", "Maria", "Doris", "Alice", "Jean", "Judy", "Frances",
)

_LAST_GENERAL: tuple[str, ...] = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter",
    "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz",
    "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales", "Murphy", "Cook",
    "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey", "Reed",
    "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks",
    "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes", "Price",
    "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez",
    "Powell", "Jenkins", "Perry", "Russell", "Sullivan", "Bell", "Coleman", "Butler",
    "Henderson", "Barnes", "Gonzales", "Fisher", "Vasquez", "Simmons", "Romero", "Jordan",
    "Patterson", "Alexander", "Hamilton", "Graham", "Reynolds", "Griffin", "Wallace", "West",
    "Cole", "Hayes", "Bryant", "Herrera", "Gibson", "Ellis", "Tran", "Medina", "Aguilar",
    "Stevens", "Murray", "Ford", "Castro", "Marshall", "Owens", "Harrison", "Fernandez",
    "Mcdonald", "Woods", "Washington", "Kennedy", "Wells", "Vargas", "Henry", "Chen",
    "Freeman", "Webb", "Tucker", "Guzman", "Burns", "Crawford", "Olson", "Simpson", "Porter",
    "Hunter", "Gordon", "Mendez", "Silva", "Shaw", "Snyder", "Mason", "Dixon", "Warren",
    "Holmes", "Rice", "Robertson", "Hunt", "Black", "Daniels", "Palmer", "Mills", "Nichols",
    "Grant", "Knight", "Ferguson", "Rose", "Stone", "Hawkins", "Dunn", "Perkins", "Hudson",
    "Spencer", "Gardner", "Stephens", "Payne", "Pierce", "Berry", "Matthews", "Arnold",
    "Wagner", "Willis", "Ray", "Watkins", "Olson", "Carroll", "Duncan", "Day", "Andrews",
    "Newman", "Bishop", "Curtis", "Lane", "Harper", "Little", "Burke", "Lane", "Stanley",
    "Boyd", "Gregory", "Haynes", "Horton", "Clayton", "Poole", "Brady", "McCarthy", "Wise",
    "Quinn", "Schmidt", "Walsh", "Schneider", "Muller", "Larson", "Benson", "Sharp",
    "Bowman", "Davidson", "May", "Day", "Schultz", "Sherman", "Wheeler", "Barber", "Kelley",
    "Franklin", "Bradley", "McCoy", "Marsh", "Chan", "Todd", "French", "Hammond", "Peacock",
    "Sinclair", "Donovan", "McKenzie", "Fitzgerald", "Donnelly", "Kerrigan", "Olsen", "Brennan",
)

_FIRST_IRISH: tuple[str, ...] = (
    "Sean", "Patrick", "Liam", "Fiona", "Niamh", "Ciaran", "Orla", "Declan", "Sinead",
    "Ronan", "Aoife", "Eoin", "Cian", "Grainne", "James", "Kate", "Colm", "Siobhan",
    "Brendan", "Emer", "Aidan", "Roisin", "Padraig", "Sorcha", "Tadhg", "Clodagh", "Darragh",
    "Eimear", "Fergal", "Grainne", "Kieran", "Maeve", "Niall", "Oisin", "Roisin", "Tiernan",
)

_FIRST_SINGAPORE: tuple[str, ...] = (
    "Wei Ming",
    "Jia En",
    "Rahman",
    "Siti",
    "Kumar",
    "Priya",
    "Jun Wei",
    "Hui Min",
    "Arjun",
    "Mei Ling",
    "Darren",
    "Nurul",
    "Ethan",
    "Shu Fen",
    "Raj",
    "Amanda",
    "Li Xuan",
    "Suresh",
)

_LAST_SINGAPORE: tuple[str, ...] = (
    "Tan",
    "Lim",
    "Ng",
    "Lee",
    "Goh",
    "Chua",
    "Ong",
    "Wong",
    "Teo",
    "Chan",
    "Cheong",
    "Ho",
    "Koh",
    "Ang",
    "Yeo",
    "Seah",
    "Phua",
    "Low",
    "Sim",
    "Tay",
)

_LATINO_FIRST_NAMES_CA: frozenset[str] = frozenset(
    {
        "Juan",
        "Diego",
        "Carlos",
        "Miguel",
        "Jose",
        "Luis",
        "Francisco",
        "Antonio",
        "Ramon",
        "Javier",
    },
)

_IRISH_LAST_NAMES_CA: frozenset[str] = frozenset(
    {
        "Kerrigan",
        "O'Brien",
        "Murphy",
        "Walsh",
        "Byrne",
        "Ryan",
        "Quinn",
        "Kelly",
        "Lynch",
        "Doyle",
    },
)

_LAST_IRISH: tuple[str, ...] = (
    "Murphy", "Kelly", "O'Brien", "Ryan", "Walsh", "Byrne", "Doyle", "Lynch", "Clarke",
    "Flynn", "Quinn", "Moore", "Kennedy", "Brennan", "Carroll", "Sheehan", "Power", "Burke",
    "Nolan", "Regan", "Hogan", "McCarthy", "Fitzgerald", "O'Connor", "O'Neill", "Gallagher",
    "Doherty", "McDonnell", "Kavanagh", "McGrath", "Healy", "Casey", "Farrell", "Duffy",
)


def site_key_from_brand(brand: dict[str, Any]) -> str:
    gid = str(brand.get("generation_identity") or "").strip()
    if gid:
        return gid
    parts = [
        str(brand.get("domain") or ""),
        str(brand.get("brand_name") or ""),
        str(brand.get("city") or ""),
        str(brand.get("postal_code") or ""),
        str(brand.get("phone") or ""),
        str(brand.get("founded_year") or ""),
    ]
    return "|".join(parts) if any(parts) else "default-site"


def _h(slot: str, site_key: str, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}|{site_key}|{slot}".encode("utf-8")).hexdigest(), 16)


def pick_full_name(
    site_key: str,
    slot: str,
    *,
    variant: str = "general",
    country: str | None = None,
) -> str:
    """Stable full name for this site + logical slot (e.g. 'consulting|team|0')."""
    c = (country or "").strip()
    if variant == "irish" or c == "Ireland":
        fi, la = _FIRST_IRISH, _LAST_IRISH
    elif c == "Singapore":
        fi, la = _FIRST_SINGAPORE, _LAST_SINGAPORE
    else:
        fi, la = _FIRST_GENERAL, _LAST_GENERAL
    h1 = _h(slot, site_key, "fn")
    h2 = _h(slot, site_key, "ln")
    fn = fi[h1 % len(fi)]
    ln = la[h2 % len(la)]
    if fn.lower() == ln.lower():
        ln = la[(h2 + 17) % len(la)]
    if c == "Canada" and fn in _LATINO_FIRST_NAMES_CA and ln in _IRISH_LAST_NAMES_CA:
        for bump in range(1, 55):
            ln = la[(h2 + bump * 23 + 11) % len(la)]
            if fn not in _LATINO_FIRST_NAMES_CA or ln not in _IRISH_LAST_NAMES_CA:
                break
    return f"{fn} {ln}"


def pick_signature_name(
    site_key: str,
    slot: str,
    *,
    variant: str = "general",
    country: str | None = None,
) -> str:
    """Attribution like 'M. Patel' for testimonials."""
    c = (country or "").strip()
    if variant == "irish" or c == "Ireland":
        fi, la = _FIRST_IRISH, _LAST_IRISH
    elif c == "Singapore":
        fi, la = _FIRST_SINGAPORE, _LAST_SINGAPORE
    else:
        fi, la = _FIRST_GENERAL, _LAST_GENERAL
    h1 = _h(slot, site_key, "sig-fn")
    h2 = _h(slot, site_key, "sig-ln")
    fn = fi[h1 % len(fi)]
    ln = la[h2 % len(la)]
    initial = (fn[:1] or "J").upper()
    return f"{initial}. {ln}"
