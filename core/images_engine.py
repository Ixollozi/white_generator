from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _pack_originals_dir(assets_dir: Path, asset_pack_id: str) -> Path:
    return assets_dir / "asset_packs" / asset_pack_id / "originals"


def apply_images(
    *,
    site_dir: Path,
    assets_dir: Path,
    images_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Returns dict to be stored in SiteContext.images.

    For upload mode, copies all files from assets/asset_packs/<id>/originals into site/img/upload/
    and returns URLs relative to site root.
    """
    cfg = images_cfg or {}
    mode = str(cfg.get("mode") or "none")
    asset_pack_id = str(cfg.get("asset_pack_id") or "").strip()

    out: dict[str, Any] = {"mode": mode, "items": []}
    if mode != "upload" or not asset_pack_id:
        return out

    src = _pack_originals_dir(assets_dir, asset_pack_id)
    if not src.is_dir():
        return out

    dst = site_dir / "img" / "upload"
    dst.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        target = dst / f.name
        if not target.exists():
            shutil.copy2(f, target)
        items.append({"name": f.name, "url": f"img/upload/{f.name}"})

    out["asset_pack_id"] = asset_pack_id
    out["items"] = items
    return out

