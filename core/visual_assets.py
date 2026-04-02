from __future__ import annotations

import hashlib
import random
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from core.image_provider import (
    pack_jpeg_paths,
    pick_pack_file,
    pil_touchup_jpeg,
    picsum_hero_urls,
    picsum_post_urls,
    resolve_image_source,
    unsplash_random_photo_url,
    wikimedia_random_file_url,
    write_placeholder_jpeg,
)

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _fetch_jpeg(url: str, dest: Path, *, timeout: float = 22.0) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WhiteGenerator/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
        if len(data) < 400:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest.is_file()
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def _seed_part(rng: random.Random, *parts: str) -> str:
    raw = "|".join(parts) + str(rng.random())
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


_PORTRAIT_COLORS = [
    "#334155", "#475569", "#1e293b", "#0f172a", "#3b0764",
    "#4a044e", "#164e63", "#134e4a", "#1e3a5f", "#312e81",
]


def _write_portrait_svg(dest: Path, initials: str, rng: random.Random) -> None:
    bg = rng.choice(_PORTRAIT_COLORS)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
        f'<rect width="400" height="400" fill="{bg}"/>'
        f'<text x="200" y="220" font-size="120" text-anchor="middle" fill="#e2e8f0" '
        f'font-family="Georgia,serif">{escape(initials)}</text></svg>'
    )
    dest.write_text(svg, encoding="utf-8")


def _hero_image_urls(rng: random.Random, brand_nm: str) -> list[str]:
    return picsum_hero_urls(rng, brand_nm)


def _maybe_touchup(dest: Path, rng: random.Random, source: str) -> None:
    if source in ("picsum", "unsplash", "wikimedia") and dest.suffix.lower() in (".jpg", ".jpeg"):
        if rng.random() < 0.65:
            pil_touchup_jpeg(dest, rng)


def materialize_site_visuals(
    site_dir: Path,
    brand: dict[str, Any],
    content: dict[str, Any],
    rng: random.Random,
    *,
    images_cfg: dict[str, Any] | None = None,
    assets_dir: Path | None = None,
) -> None:
    """Hero, team portraits, OG image, logo SVG, favicon PNGs (requires Pillow)."""
    img_root = site_dir / "img"
    img_root.mkdir(parents=True, exist_ok=True)
    brand_nm = str(brand.get("brand_name") or "site")
    slug = str(brand.get("domain") or "site").split(".")[0][:24]
    src = resolve_image_source(images_cfg)
    pack_id = str((images_cfg or {}).get("asset_pack_id") or "").strip()
    ad = Path(assets_dir) if assets_dir else Path(".")
    pack_paths = pack_jpeg_paths(ad, pack_id) if pack_id else []

    hero_path = img_root / "hero.jpg"
    got_hero = False
    if src == "placeholder":
        # One quick stock fetch when online; file is still saved under img/ (no hotlink in HTML).
        for hero_url in _hero_image_urls(rng, brand_nm)[:1]:
            if _fetch_jpeg(hero_url, hero_path, timeout=7.0):
                _maybe_touchup(hero_path, rng, "picsum")
                got_hero = True
                break
        if not got_hero:
            got_hero = write_placeholder_jpeg(hero_path, rng, 1600, 900)
    elif src == "pack" and pack_paths:
        pf = pick_pack_file(rng, pack_paths, f"hero|{brand_nm}")
        if pf and pf.is_file():
            try:
                shutil.copy2(pf, hero_path)
                got_hero = hero_path.is_file()
            except OSError:
                got_hero = False
    elif src == "unsplash":
        u = unsplash_random_photo_url(rng, 1600, 900)
        if u and _fetch_jpeg(u, hero_path):
            got_hero = True
            _maybe_touchup(hero_path, rng, src)
    elif src == "wikimedia":
        u = wikimedia_random_file_url(rng)
        if u and _fetch_jpeg(u, hero_path):
            got_hero = True
            _maybe_touchup(hero_path, rng, src)
    if not got_hero:
        for hero_url in _hero_image_urls(rng, brand_nm):
            if _fetch_jpeg(hero_url, hero_path):
                _maybe_touchup(hero_path, rng, "picsum")
                break
    brand["hero_image_src"] = "img/hero.jpg" if hero_path.is_file() else ""

    portfolio = content.get("portfolio_items")
    if isinstance(portfolio, list):
        pdir = img_root / "portfolio"
        pdir.mkdir(parents=True, exist_ok=True)
        for row in portfolio:
            if not isinstance(row, dict):
                continue
            rel = str(row.get("image_src") or "").strip()
            if not rel.startswith("img/portfolio/"):
                continue
            dest = pdir / Path(rel).name
            if dest.is_file():
                continue
            wrote = False
            if src == "placeholder":
                pu = picsum_post_urls(rng, brand_nm, dest.stem, 640, 400)
                wrote = bool(pu and _fetch_jpeg(pu[0], dest, timeout=6.0))
                if not wrote:
                    wrote = write_placeholder_jpeg(dest, rng, 640, 400)
            elif src == "pack" and pack_paths:
                pf = pick_pack_file(rng, pack_paths, f"portfolio|{brand_nm}|{dest.name}")
                if pf and pf.is_file():
                    try:
                        shutil.copy2(pf, dest)
                        wrote = dest.is_file()
                    except OSError:
                        wrote = False
            if not wrote:
                for hero_url in _hero_image_urls(rng, brand_nm):
                    if _fetch_jpeg(hero_url, dest):
                        _maybe_touchup(dest, rng, "picsum")
                        wrote = True
                        break
            if not wrote:
                write_placeholder_jpeg(dest, rng, 640, 400)

    prods = content.get("products")
    if isinstance(prods, list):
        prdir = img_root / "products"
        prdir.mkdir(parents=True, exist_ok=True)
        for row in prods:
            if not isinstance(row, dict):
                continue
            rel = str(row.get("image_src") or "").strip()
            if not rel.startswith("img/products/"):
                continue
            dest = prdir / Path(rel).name
            if dest.is_file():
                continue
            wrote = False
            slug = str(row.get("slug") or dest.stem)
            if src == "placeholder":
                wrote = False
                for url_p in picsum_post_urls(rng, brand_nm, slug, 800, 1000)[:2]:
                    if _fetch_jpeg(url_p, dest, timeout=6.0):
                        _maybe_touchup(dest, rng, "picsum")
                        wrote = True
                        break
                if not wrote:
                    wrote = write_placeholder_jpeg(dest, rng, 800, 1000)
            elif src == "pack" and pack_paths:
                pf = pick_pack_file(rng, pack_paths, f"product|{brand_nm}|{slug}")
                if pf and pf.is_file():
                    try:
                        shutil.copy2(pf, dest)
                        wrote = dest.is_file()
                    except OSError:
                        wrote = False
            if not wrote:
                for url_p in picsum_post_urls(rng, brand_nm, slug, 800, 1000):
                    if _fetch_jpeg(url_p, dest):
                        _maybe_touchup(dest, rng, "picsum")
                        wrote = True
                        break
            if not wrote:
                write_placeholder_jpeg(dest, rng, 800, 1000)

    logo_path = img_root / "logo.svg"
    letter = (brand_nm.strip()[:1] or "B").upper()
    safe_nm = escape(brand_nm)
    safe_slug = escape(slug)
    logo_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 48" role="img" aria-label="{safe_nm}">'
        f'<rect x="1" y="1" width="46" height="46" rx="10" fill="#0f172a"/>'
        f'<text x="24" y="34" font-size="26" text-anchor="middle" fill="#f8fafc" '
        f'font-family="Georgia,serif">{escape(letter)}</text>'
        f'<text x="58" y="22" font-size="15" fill="#0f172a" font-family="system-ui,sans-serif">{safe_nm}</text>'
        f'<text x="58" y="38" font-size="11" fill="#64748b" font-family="system-ui,sans-serif">{safe_slug}</text>'
        f"</svg>"
    )
    logo_path.write_text(logo_svg, encoding="utf-8")
    brand["logo_src"] = "img/logo.svg"

    team = content.get("team_items")
    if isinstance(team, list):
        tdir = img_root / "team"
        tdir.mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(team):
            if not isinstance(row, dict):
                continue
            nm = str(row.get("name") or "")
            initials = "".join(w[0].upper() for w in nm.split() if w)[:2] or "?"
            portrait_slug = _seed_part(rng, "portrait", brand_nm, nm, str(i))[:12]
            dest = tdir / f"portrait-{portrait_slug}.jpg"
            if src == "placeholder":
                tw, th = rng.choice([(420, 420), (400, 500), (480, 480)])
                seed_t = _seed_part(rng, "team", brand_nm, str(row.get("name")), str(i))
                tid = 20 + (int(hashlib.sha256(seed_t.encode()).hexdigest(), 16) % 870)
                url_t = rng.choice(
                    [
                        f"https://picsum.photos/seed/{seed_t}/{tw}/{th}.jpg",
                        f"https://picsum.photos/id/{tid}/{tw}/{th}.jpg",
                    ]
                )
                ok_ph = _fetch_jpeg(url_t, dest, timeout=6.0)
                if ok_ph:
                    _maybe_touchup(dest, rng, "picsum")
                if not ok_ph:
                    ok_ph = write_placeholder_jpeg(dest, rng, tw, th)
                if ok_ph:
                    row["photo_src"] = f"img/team/{dest.name}"
                else:
                    _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                    row["photo_src"] = f"img/team/{dest.stem}.svg"
                continue
            if src == "pack" and pack_paths:
                pf = pick_pack_file(rng, pack_paths, f"team|{brand_nm}|{i}|{nm}")
                if pf and pf.is_file():
                    try:
                        shutil.copy2(pf, dest)
                        if dest.is_file():
                            row["photo_src"] = f"img/team/{dest.name}"
                            continue
                    except OSError:
                        pass
            seed = _seed_part(rng, "team", brand_nm, str(row.get("name")), str(i))
            tw, th = rng.choice([(400, 400), (380, 480), (420, 420), (360, 450), (300, 300), (350, 350), (440, 550), (320, 400)])
            tid = 20 + (int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 870)
            url = rng.choice(
                [
                    f"https://picsum.photos/seed/{seed}/{tw}/{th}.jpg",
                    f"https://picsum.photos/id/{tid}/{tw}/{th}.jpg",
                ]
            )
            if _fetch_jpeg(url, dest):
                row["photo_src"] = f"img/team/{dest.name}"
            else:
                _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                row["photo_src"] = f"img/team/{dest.stem}.svg"

    authors = content.get("news_authors")
    if isinstance(authors, list):
        adir = img_root / "authors"
        adir.mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(authors):
            if not isinstance(row, dict):
                continue
            dest = adir / f"author-{i + 1:02d}.jpg"
            nm = str(row.get("name") or "")
            initials = "".join(w[0].upper() for w in nm.split() if w)[:2] or "?"
            if src == "placeholder":
                tw, th = rng.choice([(480, 480), (520, 520), (440, 540)])
                seed_a = _seed_part(rng, "author", brand_nm, str(row.get("name")), str(i))
                url_a = f"https://picsum.photos/seed/{seed_a}/{tw}/{th}.jpg"
                ok_a = _fetch_jpeg(url_a, dest, timeout=6.0)
                if ok_a:
                    _maybe_touchup(dest, rng, "picsum")
                if not ok_a:
                    ok_a = write_placeholder_jpeg(dest, rng, tw, th)
                if ok_a:
                    row["photo_src"] = f"img/authors/{dest.name}"
                else:
                    _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                    row["photo_src"] = f"img/authors/{dest.stem}.svg"
                continue
            if src == "pack" and pack_paths:
                pf = pick_pack_file(rng, pack_paths, f"author|{brand_nm}|{i}|{nm}")
                if pf and pf.is_file():
                    try:
                        shutil.copy2(pf, dest)
                        if dest.is_file():
                            row["photo_src"] = f"img/authors/{dest.name}"
                            continue
                    except OSError:
                        pass
            seed = _seed_part(rng, "author", brand_nm, str(row.get("name")), str(i))
            tw, th = rng.choice([(480, 480), (520, 520), (440, 540)])
            url_a = f"https://picsum.photos/seed/{seed}/{tw}/{th}.jpg"
            if _fetch_jpeg(url_a, dest):
                row["photo_src"] = f"img/authors/{dest.name}"
            else:
                _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                row["photo_src"] = f"img/authors/{dest.stem}.svg"

    posts = content.get("blog_posts")
    if isinstance(posts, list):
        pdir = img_root / "posts"
        pdir.mkdir(parents=True, exist_ok=True)
        _post_sizes = [
            (1200, 675),
            (1280, 720),
            (1000, 750),
            (1080, 1080),
            (960, 640),
        ]
        for row in posts:
            if not isinstance(row, dict):
                continue
            anchor = str(row.get("anchor") or "post").strip() or "post"
            dest = pdir / f"{anchor}.jpg"
            pw, ph = rng.choice(_post_sizes)
            ok = False
            if src == "placeholder":
                ok = False
                for url_p in picsum_post_urls(rng, brand_nm, anchor, pw, ph)[:2]:
                    if _fetch_jpeg(url_p, dest, timeout=6.0):
                        _maybe_touchup(dest, rng, "picsum")
                        ok = True
                        break
                if not ok:
                    ok = write_placeholder_jpeg(dest, rng, pw, ph)
            elif src == "pack" and pack_paths:
                pf = pick_pack_file(rng, pack_paths, f"post|{brand_nm}|{anchor}")
                if pf and pf.is_file():
                    try:
                        shutil.copy2(pf, dest)
                        ok = dest.is_file()
                    except OSError:
                        ok = False
            elif src == "unsplash":
                u = unsplash_random_photo_url(rng, pw, ph)
                if u and _fetch_jpeg(u, dest):
                    ok = True
                    _maybe_touchup(dest, rng, src)
            elif src == "wikimedia":
                u = wikimedia_random_file_url(rng)
                if u and _fetch_jpeg(u, dest):
                    ok = True
                    _maybe_touchup(dest, rng, src)
            if not ok:
                for url_p in picsum_post_urls(rng, brand_nm, anchor, pw, ph):
                    if _fetch_jpeg(url_p, dest):
                        _maybe_touchup(dest, rng, "picsum")
                        ok = True
                        break
            if ok:
                row["post_image_src"] = f"img/posts/{dest.name}"
            elif not (row.get("post_image_src") or "").strip():
                row["post_image_src"] = brand.get("hero_image_src") or brand.get("og_image_src") or ""

    titems = content.get("testimonial_items")
    if isinstance(titems, list):
        tdir = img_root / "testimonials"
        tdir.mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(titems):
            if not isinstance(row, dict):
                continue
            if not row.get("has_photo"):
                continue
            nm = str(row.get("name") or "")
            initials = "".join(w[0].upper() for w in nm.split() if w)[:2] or "?"
            tw, th = rng.choice([(200, 200), (240, 240), (180, 180)])
            dest = tdir / f"t-{i + 1:02d}.jpg"
            if src == "placeholder":
                seed_tt = _seed_part(rng, "tphoto", brand_nm, str(row.get("name")), str(i))
                url_tt = f"https://picsum.photos/seed/{seed_tt}/{tw}/{th}.jpg"
                ok_tt = _fetch_jpeg(url_tt, dest, timeout=5.0)
                if ok_tt:
                    _maybe_touchup(dest, rng, "picsum")
                if not ok_tt:
                    ok_tt = write_placeholder_jpeg(dest, rng, tw, th)
                if ok_tt:
                    row["photo_src"] = f"img/testimonials/{dest.name}"
                else:
                    _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                    row["photo_src"] = f"img/testimonials/{dest.stem}.svg"
                continue
            seed = _seed_part(rng, "tphoto", brand_nm, str(row.get("name")), str(i))
            url_t = f"https://picsum.photos/seed/{seed}/{tw}/{th}.jpg"
            if _fetch_jpeg(url_t, dest):
                row["photo_src"] = f"img/testimonials/{dest.name}"
            else:
                _write_portrait_svg(dest.with_suffix(".svg"), initials, rng)
                row["photo_src"] = f"img/testimonials/{dest.stem}.svg"

    og_path = img_root / "og-share.jpg"
    if _HAS_PIL and hero_path.is_file():
        try:
            im = Image.open(hero_path).convert("RGB")
            im = im.resize((1200, 630), Image.Resampling.LANCZOS)
            im.save(og_path, format="JPEG", quality=88)
            brand["og_image_src"] = "img/og-share.jpg"
        except OSError:
            brand["og_image_src"] = brand.get("hero_image_src") or ""
    else:
        brand["og_image_src"] = brand.get("hero_image_src") or ""

    icon_dir = site_dir
    if _HAS_PIL and hero_path.is_file():
        try:
            im = Image.open(hero_path).convert("RGBA")
            for size, name in ((32, "favicon-32x32.png"), (192, "icon-192.png")):
                thumb = im.copy()
                thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
                thumb = thumb.convert("RGBA")
                sq = Image.new("RGBA", (size, size), (15, 23, 42, 255))
                ox = (size - thumb.width) // 2
                oy = (size - thumb.height) // 2
                sq.paste(thumb, (ox, oy), thumb)
                sq.save(icon_dir / name, format="PNG")
            brand["favicon_png_32"] = "favicon-32x32.png"
            brand["icon_png_192"] = "icon-192.png"
        except OSError:
            brand["favicon_png_32"] = ""
            brand["icon_png_192"] = ""
    else:
        brand["favicon_png_32"] = ""
        brand["icon_png_192"] = ""
