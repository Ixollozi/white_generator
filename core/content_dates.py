"""Consistent synthetic dates for generated sites (blog, news, timelines).

Anchors all publish dates to ``brand["founded_year"]`` and ``brand["year"]`` so
copy does not contradict the stated company age.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any


def as_of_year(brand: dict[str, Any] | None) -> int:
    if brand:
        y = brand.get("year")
        if y is not None and str(y).strip().isdigit():
            yi = int(y)
            if 1990 <= yi <= 2100:
                return yi
    return date.today().year


def founded_year_int(brand: dict[str, Any] | None) -> int | None:
    if not brand:
        return None
    fy = brand.get("founded_year")
    if fy is None or not str(fy).strip().isdigit():
        return None
    y = int(fy)
    if y < 1970 or y > 2100:
        return None
    return y


def past_dates_in_window(
    rng: random.Random,
    n: int,
    lo: date,
    hi: date,
) -> list[tuple[str, str]]:
    if n <= 0:
        return []
    if hi < lo:
        lo, hi = hi, lo
    span_days = (hi - lo).days
    if span_days < 1:
        d = hi
        row = (f"{d.strftime('%B')} {d.day}, {d.year}", d.isoformat())
        return [row for _ in range(n)]
    pool_size = span_days + 1
    if pool_size >= n:
        offs = sorted(rng.sample(range(pool_size), n), reverse=True)
    else:
        offs = sorted([rng.randint(0, span_days) for _ in range(n)], reverse=True)
    out: list[tuple[str, str]] = []
    for o in offs:
        d = hi - timedelta(days=o)
        out.append((f"{d.strftime('%B')} {d.day}, {d.year}", d.isoformat()))
    return out


def past_dates_spread(
    rng: random.Random,
    n: int,
    *,
    brand: dict[str, Any] | None = None,
    min_span_days: int = 0,
) -> list[tuple[str, str]]:
    """Long-form blog/news: spread posts between founding (if known) and today (~2.5y window min)."""
    hi = date.today()
    fy = founded_year_int(brand)
    if fy is None:
        lo = hi - timedelta(days=900)
    else:
        cy = as_of_year(brand)
        lo = date(min(fy, cy), 1, 1)
    if min_span_days > 0:
        earliest = hi - timedelta(days=min_span_days)
        if lo > earliest:
            lo = earliest
    return past_dates_in_window(rng, n, lo, hi)


def past_dates_recent(rng: random.Random, n: int, *, brand: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Short vertical stubs: recent months, but not before ``founded_year`` (matches old 35–820 day band)."""
    hi = date.today()
    cap_lo = hi - timedelta(days=820)
    newest = hi - timedelta(days=35)
    lo = cap_lo
    fy = founded_year_int(brand)
    if fy is not None:
        cy = as_of_year(brand)
        lo = max(lo, date(min(fy, cy), 1, 1))
    if newest < lo:
        newest = hi
    return past_dates_in_window(rng, n, lo, newest)
