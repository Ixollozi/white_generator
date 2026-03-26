from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_build_manifest(site_dir: Path, payload: dict[str, Any]) -> None:
    path = site_dir / "build-manifest.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
