from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape


def load_template_manifest(template_dir: Path) -> dict[str, Any]:
    path = template_dir / "template.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing template.yaml in {template_dir}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("template.yaml must be a mapping")
    return data


def make_template_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_string(env: Environment, source: str, variables: dict[str, Any]) -> str:
    return env.from_string(source).render(**variables)
