from __future__ import annotations

import random
import string
from pathlib import Path
from typing import Any


def _rand_name(rng: random.Random, prefix: str, ext: str) -> str:
    suffix = "".join(rng.choice(string.ascii_lowercase) for _ in range(6))
    return f"{prefix}-{suffix}.{ext}"


def write_noise_assets(
    site_dir: Path,
    rng: random.Random,
    noise_cfg: dict[str, Any],
) -> list[str]:
    """Create empty-ish css/js files up to configured max. Returns relative paths."""
    css_max = int(noise_cfg.get("extra_css_max") or 0)
    js_max = int(noise_cfg.get("extra_js_max") or 0)
    written: list[str] = []
    css_dir = site_dir / "css"
    js_dir = site_dir / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(css_max):
        name = _rand_name(rng, "layer", "css")
        p = css_dir / name
        p.write_text(
            "/* generated */\n.noise-placeholder{display:block}\n",
            encoding="utf-8",
        )
        written.append(f"css/{name}")

    for _ in range(js_max):
        name = _rand_name(rng, "chunk", "js")
        p = js_dir / name
        p.write_text(
            "// generated\n(function(){})();\n",
            encoding="utf-8",
        )
        written.append(f"js/{name}")

    return written
