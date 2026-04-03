from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import random
import yaml


@dataclass
class ComponentPick:
    component_type: str
    variant_file: str
    html: str


def _load_meta(components_dir: Path, component_type: str) -> dict[str, Any]:
    meta_path = components_dir / component_type / "meta.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing components/{component_type}/meta.yaml")
    with meta_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid meta.yaml for {component_type}")
    return data


def list_required_vars(components_dir: Path, component_type: str) -> list[str]:
    meta = _load_meta(components_dir, component_type)
    req = meta.get("required_vars") or []
    if not isinstance(req, list):
        return []
    return [str(x) for x in req]


def pick_component(
    rng: random.Random,
    components_dir: Path,
    component_type: str,
    variables: dict[str, Any],
    strict: bool,
) -> ComponentPick:
    meta = _load_meta(components_dir, component_type)
    variants = list(meta.get("variants") or [])
    vid = str(variables.get("vertical_id") or "").strip()
    if component_type == "contact_block" and vid in ("cafe_restaurant", "cleaning"):
        def _is_dispatch_variant(v: Any) -> bool:
            fn = v if isinstance(v, str) else str((v or {}).get("file") or (v or {}).get("path") or "")
            return fn == "contact_block_3.html"

        variants = [v for v in variants if not _is_dispatch_variant(v)]
    if not variants:
        raise ValueError(f"No variants for component type {component_type}")
    choice = rng.choice(variants)
    if isinstance(choice, str):
        filename = choice
    elif isinstance(choice, dict):
        filename = str(choice.get("file") or choice.get("path"))
    else:
        raise ValueError(f"Bad variant entry in {component_type}/meta.yaml")
    required = meta.get("required_vars") or []
    missing = [k for k in required if k not in variables or variables[k] in (None, "")]
    if missing:
        msg = f"Component {component_type} missing vars: {missing}"
        if strict:
            raise KeyError(msg)
        for k in missing:
            variables.setdefault(k, "")
    path = components_dir / component_type / filename
    html = path.read_text(encoding="utf-8")
    return ComponentPick(component_type, filename, html)
