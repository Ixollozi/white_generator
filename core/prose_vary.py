"""Deterministic prose variation helpers (no LLM): register, local detail, paragraph shape, opener dedupe.

Optional brand/merged keys:
- prose_humanize (default on): master switch for longform/news touches.
- prose_micro_imperfections: light contractions / speech-like punctuation.
- prose_chatty_level: \"low\" (default) or \"medium\" — more hedges, punches, and conversational hits.
"""

from __future__ import annotations

import html as html_lib
import random
import re
from datetime import date
from typing import Any

Register = str

BANNED_PARAGRAPH_PREFIXES: tuple[str, ...] = (
    "we drafted",
    "short answer:",
    "this month’s note",
    "this month's note",
    "for teams",
    "when working",
    "internally we file",
    "field note from",
)


def pick_register(rng: random.Random) -> Register:
    return rng.choice(["formal", "neutral", "conversational"])


def prose_humanize_enabled(brand: dict[str, Any] | None, merged: dict[str, Any] | None = None) -> bool:
    if merged and merged.get("prose_humanize") is False:
        return False
    if brand and brand.get("prose_humanize") is False:
        return False
    return True


def prose_micro_imperfections_enabled(brand: dict[str, Any] | None, merged: dict[str, Any] | None = None) -> bool:
    if merged and merged.get("prose_micro_imperfections"):
        return True
    if brand and brand.get("prose_micro_imperfections"):
        return True
    return False


def season_phrase(_brand: dict[str, Any] | None, rng: random.Random) -> str:
    m = date.today().month
    if m in (12, 1, 2):
        return rng.choice(["winter weather", "cold-season weeks", "short-day scheduling"])
    if m in (3, 4, 5):
        return rng.choice(["spring thaw", "mud-season access", "allergy-heavy weeks"])
    if m in (6, 7, 8):
        return rng.choice(["peak heat", "summer vacation traffic", "high-demand season"])
    return rng.choice(["fall rain", "back-to-school traffic", "year-end crunch"])


def random_time_window(rng: random.Random) -> str:
    return rng.choice(
        [
            "8:30–10:30",
            "9:00–noon",
            "after lunch",
            "first calls around 9:15",
            "a mid-morning block",
            "the early slot before routes fill",
        ],
    )


def pick_zone_fragment(brand: dict[str, Any] | None, rng: random.Random) -> str:
    if not brand:
        return ""
    z = brand.get("service_area_zones")
    if isinstance(z, list) and z:
        return str(rng.choice(z)).strip()
    return ""


def inject_local_detail(text: str, brand: dict[str, Any] | None, rng: random.Random) -> str:
    """Append one short, plausible local clause (city, zone, season, or time window)."""
    t = (text or "").rstrip()
    if not t or "<" in t:
        return text
    city = str((brand or {}).get("city") or "").strip()
    region = str((brand or {}).get("region") or "").strip()
    zone = pick_zone_fragment(brand, rng)
    bits: list[str] = []
    r = rng.random()
    if r < 0.34 and zone:
        bits.append(
            rng.choice(
                [
                    f" Near {zone}, narrow-street parking still surprises first-time visitors.",
                    f" Crews route through {zone} often enough that arrival estimates stay honest.",
                    f" In {zone}, building access rules vary block by block — we confirm before we dispatch.",
                ],
            ),
        )
    elif r < 0.52 and city:
        bits.append(
            rng.choice(
                [
                    f" In {city}, {season_phrase(brand, rng)} moves schedules faster than most clients expect.",
                    f" Around {city}, we batch {random_time_window(rng)} calls when demand spikes.",
                ],
            ),
        )
    elif r < 0.62 and region and city:
        bits.append(f" Across {region}, we keep the same contact tree {city} clients already use.")
    elif r < 0.72 and city:
        bits.append(
            rng.choice(
                [
                    f" Same-day triage still happens — just not always in the {random_time_window(rng)} window.",
                    " Weather and traffic routinely shift the second stop of the day; dispatch texts when that happens.",
                ],
            ),
        )
    else:
        return text
    frag = rng.choice(bits)
    if frag.strip() in t:
        return text
    join = "" if t.endswith((".", "!", "?")) else "."
    return f"{t}{join}{frag}"


def paragraph_starts_stale(s: str) -> bool:
    low = (s or "").strip().lower()
    return any(low.startswith(p) for p in BANNED_PARAGRAPH_PREFIXES)


def first_sentence_opener_key(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    m = re.match(r"^([^.!?]+)", t)
    chunk = m.group(1) if m else t
    words = chunk.split()[:3]
    return " ".join(words).lower()


def dedupe_paragraph_openers(paragraphs: list[str], rng: random.Random) -> list[str]:
    """If a paragraph repeats the same 2–3 word opener as an earlier one, rewrite the first sentence lightly."""
    seen: set[str] = set()
    out: list[str] = []
    for p in paragraphs:
        if not isinstance(p, str) or not p.strip():
            out.append(p)
            continue
        key = first_sentence_opener_key(p)
        if key and key in seen and len(key) > 2:
            alt = _nudge_opener_sentence(p, rng)
            out.append(alt)
            seen.add(first_sentence_opener_key(alt))
        else:
            out.append(p)
            if key:
                seen.add(key)
    return out


def _nudge_opener_sentence(para: str, rng: random.Random) -> str:
    """Prefix with a low-key transition so the opener key changes."""
    transitions = [
        "On our side, ",
        "From the field, ",
        "Practically speaking, ",
        "In plain terms, ",
        "Behind the scenes, ",
    ]
    t = para.strip()
    if not t:
        return para
    return rng.choice(transitions) + t[0].lower() + t[1:] if len(t) > 1 else rng.choice(transitions) + t


def vary_paragraph_shape(paragraphs: list[str], rng: random.Random) -> list[str]:
    """Merge short paragraphs, split long ones on '; ', or insert a one-line punch (plain text only)."""
    out = [p for p in paragraphs if isinstance(p, str) and p.strip()]
    if len(out) < 2:
        return out
    if rng.random() < 0.38:
        for i in range(len(out) - 1):
            if len(out[i]) < 130 and len(out[i + 1]) < 130:
                merged = out[i].rstrip().rstrip(".") + " " + out[i + 1].lstrip()
                out = out[:i] + [merged] + out[i + 2 :]
                break
    if rng.random() < 0.3 and len(out) >= 2:
        for i, block in enumerate(out):
            if "; " in block and len(block) > 220:
                a, b = block.split("; ", 1)
                if len(a) > 40 and len(b) > 40:
                    out = out[:i] + [a.strip() + ".", b.strip().lstrip()] + out[i + 1 :]
                    break
    if rng.random() < 0.28 and len(out) >= 2:
        punches = [
            "Worth saying once.",
            "That part matters.",
            "No magic — just habit.",
            "Details save time.",
            "Paper beats memory.",
            "Usually.",
            "Same drill.",
            "Still applies.",
            "Ask first.",
        ]
        ins = rng.randint(1, max(1, len(out) - 1))
        out.insert(ins, rng.choice(punches))
    return out


def prose_chatty_strength(brand: dict[str, Any] | None, merged: dict[str, Any] | None = None) -> float:
    """Higher value → more hedges, punches, and conversational hits (see prose_chatty_level: low|medium)."""
    raw = str((merged or {}).get("prose_chatty_level") or (brand or {}).get("prose_chatty_level") or "low").strip().lower()
    return 1.0 if raw == "medium" else 0.55


def apply_conversational_leadin(
    text: str,
    rng: random.Random,
    *,
    p_apply: float | None = None,
    chatty_strength: float = 0.55,
) -> str:
    base_p = 0.22 if p_apply is None else p_apply
    p = min(0.62, base_p * (0.75 + chatty_strength))
    if rng.random() > p:
        return text
    t = text.strip()
    if not t:
        return text
    low = t.lower()
    if low.startswith(("honestly", "look ", "small thing", "quick note", "real talk")):
        return text
    lead = rng.choice(
        [
            "Honestly, ",
            "Look — ",
            "Small thing: ",
            "Quick note: ",
            "Real talk: ",
            "Between us, ",
        ],
    )
    return lead + (t[0].lower() + t[1:] if len(t) > 1 else t)


def apply_micro_imperfections(text: str, rng: random.Random) -> str:
    """Light contractions / speech-like comma — optional, trust-sensitive."""
    if rng.random() > 0.35:
        return text
    t = text
    if rng.random() < 0.5:
        t = re.sub(r"\bWe have\b", "We've", t, count=1)
        t = re.sub(r"\bIt is\b", "It's", t, count=1)
        t = re.sub(r"\bThat is\b", "That's", t, count=1)
        t = re.sub(r"\bYou will\b", "You'll", t, count=1)
    if rng.random() < 0.22 and "," in t:
        # insert a single comma before a short clause (very conservative)
        m = re.search(r"^(We|You|I) (\w+ \w+)", t)
        if m and m.end() < len(t) - 10:
            pos = m.end()
            if t[pos : pos + 1] != ",":
                t = t[:pos] + "," + t[pos:]
    return t


def rewrite_if_stale_opener(paragraph: str, alternatives: list[str], rng: random.Random) -> str:
    if not paragraph_starts_stale(paragraph):
        return paragraph
    pool = [a for a in alternatives if a.strip() and not paragraph_starts_stale(a.strip())]
    if not pool:
        return paragraph
    return rng.choice(pool)


def strip_inner_paragraph_text(block: str) -> str | None:
    s = (block or "").strip()
    m = re.fullmatch(r"<p>(.*)</p>", s, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    inner = m.group(1)
    if "<" in inner:
        inner = re.sub(r"<[^>]+>", " ", inner)
    return html_lib.unescape(inner).strip()


def wrap_paragraph_html(plain: str) -> str:
    from xml.sax.saxutils import escape

    return f"<p>{escape(plain.strip())}</p>"


def apply_inject_to_random_html_paragraphs(
    sections: list[dict[str, Any]],
    brand: dict[str, Any] | None,
    rng: random.Random,
    *,
    max_touch: int = 2,
) -> None:
    """Pick 1–2 simple <p> blocks across sections and append inject_local_detail."""
    candidates: list[tuple[int, int]] = []
    for si, sec in enumerate(sections):
        paras = sec.get("paragraphs_html")
        if not isinstance(paras, list):
            continue
        for pi, block in enumerate(paras):
            if not isinstance(block, str):
                continue
            plain = strip_inner_paragraph_text(block)
            if plain and len(plain) > 60:
                candidates.append((si, pi))
    rng.shuffle(candidates)
    n = rng.randint(1, min(max_touch, max(1, len(candidates))))
    for si, pi in candidates[:n]:
        paras = sections[si]["paragraphs_html"]
        block = paras[pi]
        plain = strip_inner_paragraph_text(block)
        if not plain:
            continue
        new_plain = inject_local_detail(plain, brand, rng)
        if new_plain != plain:
            paras[pi] = wrap_paragraph_html(new_plain)


def vary_first_section_plain_shape(sections: list[dict[str, Any]], rng: random.Random) -> None:
    """Run vary_paragraph_shape on plain text of first section's <p> blocks, then re-wrap."""
    if not sections:
        return
    paras = sections[0].get("paragraphs_html")
    if not isinstance(paras, list) or len(paras) < 2:
        return
    plains: list[str] = []
    indices: list[int] = []
    for i, block in enumerate(paras):
        pl = strip_inner_paragraph_text(block) if isinstance(block, str) else None
        if pl:
            plains.append(pl)
            indices.append(i)
    if len(plains) < 2:
        return
    shaped = vary_paragraph_shape(plains, rng)
    if len(shaped) == len(indices):
        for idx, plain in zip(indices, shaped):
            paras[idx] = wrap_paragraph_html(plain)
    else:
        start, end = indices[0], indices[-1]
        new_blocks = [wrap_paragraph_html(s) for s in shaped]
        paras[start : end + 1] = new_blocks


def massage_first_html_paragraph(
    sections: list[dict[str, Any]],
    rng: random.Random,
    *,
    register: str,
    micro: bool,
    chatty_strength: float = 0.55,
) -> None:
    if not sections:
        return
    paras = sections[0].get("paragraphs_html")
    if not isinstance(paras, list) or not paras:
        return
    first = paras[0]
    if not isinstance(first, str):
        return
    plain = strip_inner_paragraph_text(first)
    if not plain:
        return
    if register == "conversational":
        plain = apply_conversational_leadin(plain, rng, chatty_strength=chatty_strength)
    elif register == "neutral" and rng.random() < 0.08 * chatty_strength:
        plain = apply_conversational_leadin(plain, rng, p_apply=0.12, chatty_strength=chatty_strength)
    if micro:
        plain = apply_micro_imperfections(plain, rng)
    paras[0] = wrap_paragraph_html(plain)


def maybe_prepend_hedge(text: str, rng: random.Random, *, strength: float = 0.55) -> str:
    if rng.random() > 0.14 * (0.7 + strength):
        return text
    t = text.strip()
    if not t or "<" in t:
        return text
    hedge = rng.choice(
        [
            "Usually, ",
            "Sometimes ",
            "Last week, ",
            "Mostly, ",
            "In practice, ",
            "Often enough, ",
        ],
    )
    return hedge + (t[0].lower() + t[1:] if len(t) > 1 else t)


def append_numeric_texture_clause(text: str, rng: random.Random) -> str:
    if rng.random() > 0.2:
        return text
    t = text.rstrip()
    if not t or "<" in t:
        return text
    frag = rng.choice(
        [
            " First pass is often under 15 minutes if access is clean.",
            " Budget two days if paperwork has to cross two desks.",
            " We’ve seen a roughly 40% drop in repeat calls once the checklist sticks.",
            " Same-day still happens — not always in the first 90 minutes.",
            " A ten-minute phone save beats a two-hour reschedule.",
        ],
    )
    if frag.strip() in t:
        return text
    join = "" if t.endswith((".", "!", "?")) else "."
    return f"{t}{join}{frag}"


def append_mundane_delay_clause(text: str, brand: dict[str, Any] | None, rng: random.Random) -> str:
    if rng.random() > 0.16:
        return text
    t = text.rstrip()
    if not t or "<" in t:
        return text
    city = str((brand or {}).get("city") or "").strip()
    loc = city or "the route"
    frag = rng.choice(
        [
            f" Rain last week nudged one stop in {loc} — normal chaos, not a crisis.",
            " Mondays run late more often than we admit.",
            f" {season_phrase(brand, rng).capitalize()} still eats the first slot some weeks.",
            " Traffic around school dismissal shifts the second arrival — we text when that happens.",
            " One van running behind echoes through the whole afternoon board.",
        ],
    )
    join = "" if t.endswith((".", "!", "?")) else "."
    return f"{t}{join}{frag}"


def vary_section_plain_shape(
    sections: list[dict[str, Any]],
    section_index: int,
    rng: random.Random,
) -> None:
    if section_index < 0 or section_index >= len(sections):
        return
    paras = sections[section_index].get("paragraphs_html")
    if not isinstance(paras, list) or len(paras) < 2:
        return
    plains: list[str] = []
    indices: list[int] = []
    for i, block in enumerate(paras):
        pl = strip_inner_paragraph_text(block) if isinstance(block, str) else None
        if pl:
            plains.append(pl)
            indices.append(i)
    if len(plains) < 2:
        return
    shaped = vary_paragraph_shape(plains, rng)
    if len(shaped) == len(indices):
        for idx, plain in zip(indices, shaped):
            paras[idx] = wrap_paragraph_html(plain)
    else:
        start, end = indices[0], indices[-1]
        paras[start : end + 1] = [wrap_paragraph_html(s) for s in shaped]


_ULTRA_SHORT_PUNCHES: tuple[str, ...] = (
    "Worth a bookmark.",
    "Same as last month.",
    "No magic.",
    "Paper wins.",
    "Details matter.",
    "Ask early.",
    "We mean it.",
    "Check the date.",
    "Still true.",
)

_LOW_KEY_FINALS: tuple[str, ...] = (
    "We'll refresh this if our process moves.",
    "Ping us if your site breaks the template.",
    "More later if the same questions keep landing.",
    "Stopping here — the rest is situational.",
    "If this ages badly, check the byline date.",
)


def apply_blog_post_depth_pass(
    sections: list[dict[str, Any]],
    brand: dict[str, Any] | None,
    rng: random.Random,
    *,
    register: str,
    micro: bool,
    chatty_strength: float = 0.55,
) -> None:
    """Extra variation across sections: shape, hedges, punches, mundane/numeric clauses, soft endings."""
    if not sections:
        return
    nsec = len(sections)
    idxs = list(range(nsec))
    rng.shuffle(idxs)
    n_shape = rng.randint(1, min(3, nsec))
    for si in idxs[:n_shape]:
        if rng.random() < 0.72:
            vary_section_plain_shape(sections, si, rng)

    candidates: list[tuple[int, int]] = []
    for si, sec in enumerate(sections):
        paras = sec.get("paragraphs_html")
        if not isinstance(paras, list):
            continue
        for pi, block in enumerate(paras):
            if not isinstance(block, str):
                continue
            plain = strip_inner_paragraph_text(block)
            if plain and 35 < len(plain) < 420:
                candidates.append((si, pi))
    rng.shuffle(candidates)
    n_touch = rng.randint(1, min(4, max(1, len(candidates))))
    formal = register == "formal"
    for si, pi in candidates[:n_touch]:
        paras = sections[si]["paragraphs_html"]
        block = paras[pi]
        plain = strip_inner_paragraph_text(block)
        if not plain:
            continue
        if not formal and rng.random() < 0.34 * chatty_strength:
            plain = maybe_prepend_hedge(plain, rng, strength=chatty_strength)
        if rng.random() < 0.22 * chatty_strength:
            plain = append_numeric_texture_clause(plain, rng)
        if not formal and rng.random() < 0.2 * chatty_strength:
            plain = append_mundane_delay_clause(plain, brand, rng)
        if register == "conversational" and pi > 0 and rng.random() < 0.18 * chatty_strength:
            plain = apply_conversational_leadin(plain, rng, chatty_strength=chatty_strength)
        if micro and rng.random() < 0.25:
            plain = apply_micro_imperfections(plain, rng)
        paras[pi] = wrap_paragraph_html(plain)

    if rng.random() < 0.38 * chatty_strength:
        si = rng.randrange(nsec)
        paras = sections[si].get("paragraphs_html")
        if isinstance(paras, list) and paras:
            ins = rng.randint(0, len(paras))
            paras.insert(ins, wrap_paragraph_html(rng.choice(_ULTRA_SHORT_PUNCHES)))

    if rng.random() < 0.24 * (0.6 + chatty_strength):
        si = rng.randrange(nsec)
        paras = sections[si].get("paragraphs_html")
        if isinstance(paras, list) and len(paras) >= 2:
            pi = rng.randint(0, len(paras) - 2)
            p0 = strip_inner_paragraph_text(paras[pi]) or ""
            p1 = strip_inner_paragraph_text(paras[pi + 1]) or ""
            w0 = p0.split()[:2]
            if len(w0) >= 1 and rng.random() < 0.5:
                stub = f"{w0[0]} — same thread."
                paras.insert(pi + 1, wrap_paragraph_html(stub))

    last_sec = sections[-1].get("paragraphs_html")
    if isinstance(last_sec, list) and last_sec and rng.random() < 0.22 * chatty_strength:
        last_block = last_sec[-1]
        if isinstance(last_block, str):
            plain = strip_inner_paragraph_text(last_block)
            if plain and len(plain) > 120 and rng.random() < 0.55:
                last_sec[-1] = wrap_paragraph_html(rng.choice(_LOW_KEY_FINALS))


def news_local_anchor_sentence(city: str, brand: dict[str, Any] | None, rng: random.Random) -> str:
    loc = (city or "").strip() or "the region"
    geo = (brand or {}).get("geo_profile") if isinstance((brand or {}).get("geo_profile"), dict) else {}
    seeds = geo.get("topic_seeds") if isinstance(geo, dict) else None
    extra = ""
    if isinstance(seeds, list) and seeds and rng.random() < 0.45:
        extra = f" ({rng.choice([str(s) for s in seeds if str(s).strip()])})"
    return rng.choice(
        [
            f"Editors on the {loc} desk watch how this story lands with readers who live it, not just scan it{extra}.",
            f"Local context in {loc} still shifts faster than national framing — we note what we can verify{extra}.",
            f"For {loc}, the through-line is practical: what changes next week, not only what changed yesterday.",
        ],
    )
