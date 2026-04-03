from __future__ import annotations

import hashlib
import random
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.image_provider import resolve_image_source, write_placeholder_jpeg


def _gallery_basename_prefix(vertical_id: str) -> str:
    """Avoid generic 'venue-*' for professional sites; neutral names elsewhere."""
    vid = (vertical_id or "").strip()
    if vid in ("legal", "consulting", "medical", "dental", "accounting"):
        return "office"
    if vid in ("cafe_restaurant", "news", "clothing"):
        return "gallery"
    return "site"


def materialize_gallery_images(
    site_dir: Path,
    content: dict[str, Any],
    rng: random.Random,
    brand: dict[str, Any] | None = None,
    images_cfg: dict[str, Any] | None = None,
) -> None:
    """
    Write gallery JPEGs under img/gallery/: local placeholders by default; remote stock only when
    image_source is picsum/unsplash/wikimedia and fetch succeeds.
    """
    items = content.get("gallery_items")
    if not isinstance(items, list):
        return
    gdir = site_dir / "img" / "gallery"
    gdir.mkdir(parents=True, exist_ok=True)
    brand_nm = str((brand or {}).get("brand_name") or content.get("brand_name") or "site")
    vid = str(content.get("vertical_id") or "").strip()
    prefix = _gallery_basename_prefix(vid)
    src = resolve_image_source(images_cfg)
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        cap = str(raw.get("caption") or f"photo-{i + 1}")
        seed = hashlib.sha256(f"{brand_nm}|{i}|{cap}|{rng.random()}".encode()).hexdigest()[:20]
        dest = gdir / f"{prefix}-{i + 1:02d}.jpg"
        w, hg = rng.choice([(900, 600), (880, 600), (960, 640), (1024, 683)])
        ok = False
        if src == "placeholder":
            ok = write_placeholder_jpeg(dest, rng, w, hg)
        elif src == "picsum":
            h = int(hashlib.sha256(f"g|{brand_nm}|{i}".encode()).hexdigest(), 16)
            pic_id = 30 + (h % 850)
            for u in (
                f"https://picsum.photos/seed/{seed}/{w}/{hg}.jpg",
                f"https://picsum.photos/id/{pic_id}/{w}/{hg}.jpg",
                f"https://picsum.photos/{w}/{hg}?random={seed}",
            ):
                try:
                    urllib.request.urlretrieve(u, dest)  # noqa: S310
                    if dest.is_file() and dest.stat().st_size > 500:
                        ok = True
                        break
                except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                    continue
        if not ok:
            ok = write_placeholder_jpeg(dest, rng, w, hg)
        raw["image_src"] = f"img/gallery/{dest.name}" if ok or dest.is_file() else ""
