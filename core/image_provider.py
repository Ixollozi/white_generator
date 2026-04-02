from __future__ import annotations

import hashlib
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageEnhance, ImageFilter

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    ImageFilter = None  # type: ignore[misc, assignment]


def resolve_image_source(images_cfg: dict[str, Any] | None) -> str:
    """Remote/stock strategy: picsum | placeholder | unsplash | wikimedia | pack."""
    cfg = images_cfg if isinstance(images_cfg, dict) else {}
    src = str(cfg.get("image_source") or "").strip().lower()
    if src in ("placeholder", "picsum", "unsplash", "wikimedia", "pack"):
        return src
    mode = str(cfg.get("mode") or "none").strip().lower()
    if mode == "web":
        return "picsum"
    if mode == "upload" and str(cfg.get("asset_pack_id") or "").strip():
        return "pack"
    # Default: local placeholder JPEGs/SVGs (no hotlinked stock URLs in shipped HTML).
    return "placeholder"


def pack_jpeg_paths(assets_dir: Path, asset_pack_id: str) -> list[Path]:
    root = assets_dir / "asset_packs" / asset_pack_id / "originals"
    if not root.is_dir():
        return []
    out: list[Path] = []
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            out.append(f)
    return out


def _seed_part(rng: random.Random, *parts: str) -> str:
    raw = "|".join(parts) + str(rng.random())
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def picsum_post_urls(rng: random.Random, brand_nm: str, anchor: str, pw: int, ph: int) -> list[str]:
    seed = _seed_part(rng, "postimg", brand_nm, anchor)
    gray = "/grayscale" if rng.random() < 0.12 else ""
    return [
        f"https://picsum.photos/seed/{seed}/{pw}/{ph}.jpg{gray}",
        f"https://picsum.photos/{pw}/{ph}?random={seed}",
    ]


def picsum_hero_urls(rng: random.Random, brand_nm: str) -> list[str]:
    seed = _seed_part(rng, "hero", brand_nm)
    h = int(hashlib.sha256(f"picid|{brand_nm}".encode("utf-8")).hexdigest(), 16)
    pic_id = 11 + (h % 880)
    w, hg = 1600, 900
    w2, hg2 = 1536, 864
    grayscale = "/grayscale" if rng.random() < 0.15 else ""
    blur = f"?blur={rng.randint(1, 3)}" if rng.random() < 0.1 else ""
    return [
        f"https://picsum.photos/seed/{seed}/{w}/{hg}.jpg{grayscale}",
        f"https://picsum.photos/id/{pic_id}/{w}/{hg}.jpg",
        f"https://picsum.photos/seed/{_seed_part(rng, 'h2', brand_nm)}/{w2}/{hg2}.jpg{blur}",
        f"https://picsum.photos/{w}/{hg}?random={seed}",
    ]


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def unsplash_random_photo_url(rng: random.Random, width: int, height: int) -> str | None:
    key = (os.environ.get("UNSPLASH_ACCESS_KEY") or "").strip()
    if not key:
        return None
    params = urllib.parse.urlencode({"orientation": "landscape", "w": width, "h": height})
    url = f"https://api.unsplash.com/photos/random?{params}"
    try:
        data = _http_json(url, headers={"Authorization": f"Client-ID {key}"})
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    urls = data.get("urls")
    if isinstance(urls, dict):
        u = urls.get("regular") or urls.get("full")
        if isinstance(u, str) and u.startswith("http"):
            return u
    return None


def wikimedia_random_file_url(rng: random.Random) -> str | None:
    """Pick a Commons file URL via generator=search (no API key)."""
    queries = [
        "city skyline photograph",
        "landscape nature photograph",
        "public building architecture",
        "street photography urban",
    ]
    q = rng.choice(queries)
    api = (
        "https://commons.wikimedia.org/w/api.php?format=json&action=query"
        "&generator=search&gsrnamespace=6&gsrlimit=8&prop=imageinfo&iiprop=url"
        "&iiurlwidth=1200&gsrsearch="
        + urllib.parse.quote(q)
    )
    try:
        data = _http_json(api, timeout=30)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    qd = data.get("query") if isinstance(data, dict) else None
    pages = qd.get("pages") if isinstance(qd, dict) else None
    if not isinstance(pages, dict) or not pages:
        return None
    candidates: list[str] = []
    for _pid, page in pages.items():
        if not isinstance(page, dict):
            continue
        ii = page.get("imageinfo")
        if isinstance(ii, list) and ii:
            info = ii[0]
            if isinstance(info, dict):
                u = info.get("url")
                if isinstance(u, str) and u.startswith("http"):
                    candidates.append(u)
    return rng.choice(candidates) if candidates else None


def _noise_grayscale(w: int, h: int, rng: random.Random) -> Image.Image:
    """Grayscale noise layer; prefers Pillow effect_noise, falls back to pixel fill on a small buffer."""
    w = max(8, min(w, 512))
    h = max(8, min(h, 512))
    try:
        sigma = float(rng.uniform(3.5, 14.0))
        n = Image.effect_noise((w, h), sigma)
        if n.mode != "L":
            n = n.convert("L")
        return n
    except (AttributeError, TypeError, ValueError):
        im = Image.new("L", (w, h))
        px = im.load()
        for yy in range(h):
            for xx in range(w):
                px[xx, yy] = rng.randint(0, 255)
        return im


def write_placeholder_jpeg(dest: Path, rng: random.Random, w: int, h: int) -> bool:
    """Offline-friendly JPEG: multi-stop gradient + film grain (not a flat color block)."""
    if not _HAS_PIL:
        return False
    try:
        w = max(32, min(int(w), 4000))
        h = max(32, min(int(h), 4000))
        # Muted, plausible photo-like hues (not neon)
        c1 = (rng.randint(28, 95), rng.randint(38, 115), rng.randint(55, 145))
        c2 = (rng.randint(45, 130), rng.randint(42, 118), rng.randint(40, 110))
        c3 = (rng.randint(35, 105), rng.randint(55, 125), rng.randint(75, 155))

        mask_h = Image.linear_gradient("L").resize((w, h), Image.Resampling.LANCZOS)
        r = mask_h.point(lambda x: int(c1[0] + (c2[0] - c1[0]) * x / 255.0))
        g = mask_h.point(lambda x: int(c1[1] + (c2[1] - c1[1]) * x / 255.0))
        bch = mask_h.point(lambda x: int(c1[2] + (c2[2] - c1[2]) * x / 255.0))
        base = Image.merge("RGB", (r, g, bch))

        mask_v = (
            Image.linear_gradient("L")
            .transpose(Image.Transpose.ROTATE_90)
            .resize((w, h), Image.Resampling.LANCZOS)
        )
        strength = rng.uniform(0.14, 0.34)
        comp_mask = mask_v.point(lambda p: min(255, int(p * strength)))
        tint = Image.new("RGB", (w, h), c3)
        base = Image.composite(tint, base, comp_mask)

        nw = max(96, w // 4)
        nh = max(96, h // 4)
        noise = _noise_grayscale(nw, nh, rng).resize((w, h), Image.Resampling.LANCZOS)
        grain = Image.merge("RGB", (noise, noise, noise))
        im = Image.blend(base, grain, rng.uniform(0.09, 0.22))

        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.94, 1.14))
        im = ImageEnhance.Color(im).enhance(rng.uniform(0.82, 1.18))
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.92, 1.06))
        if ImageFilter is not None and rng.random() < 0.55:
            im = im.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.35, 1.1)))

        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, format="JPEG", quality=90)
        return dest.is_file()
    except OSError:
        return False


def pick_pack_file(rng: random.Random, paths: list[Path], seed_key: str) -> Path | None:
    if not paths:
        return None
    idx = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % len(paths)
    return paths[idx]


def pil_touchup_jpeg(path: Path, rng: random.Random) -> None:
    """Lightweight crop-safe adjustment after download."""
    if not _HAS_PIL or not path.is_file():
        return
    try:
        im = Image.open(path).convert("RGB")
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.92, 1.06))
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.95, 1.08))
        im.save(path, format="JPEG", quality=90)
    except OSError:
        pass
