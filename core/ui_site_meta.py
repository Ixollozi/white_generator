from __future__ import annotations

import json
from pathlib import Path
from typing import Any

UI_SITE_META_NAME = ".ui-site-meta.json"


def write_ui_site_meta(site_dir: Path, payload: dict[str, Any]) -> None:
    """Minimal metadata for local UI (list sites). Not intended for public deploy — excluded from zip."""
    path = site_dir / UI_SITE_META_NAME
    slim = {
        k: payload[k]
        for k in ("build_id", "template_id", "vertical_id", "theme_pack_folder", "brand_name")
        if payload.get(k) is not None
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(slim, f, indent=2, ensure_ascii=False)
        f.write("\n")
