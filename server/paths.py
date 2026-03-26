from __future__ import annotations

import re
from pathlib import Path

_OUTPUT_SUBDIR_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_SITE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_output_path() -> Path:
    return project_root() / "output"


def resolve_output_path(output_dir: str | None) -> Path:
    root = project_root()
    if not output_dir or output_dir.strip() in ("", "output"):
        return default_output_path()
    name = output_dir.strip().replace("\\", "/").split("/")[-1]
    if not _OUTPUT_SUBDIR_RE.match(name):
        raise ValueError("Invalid output directory name")
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise ValueError("output_dir must stay under project root") from e
    return candidate


def validate_site_folder_name(name: str) -> str:
    if not name or not _SITE_NAME_RE.match(name):
        raise ValueError("Invalid site folder name")
    return name


def site_dir_for_name(site_name: str, output_path: Path | None = None) -> Path:
    name = validate_site_folder_name(site_name)
    base = output_path if output_path is not None else default_output_path()
    path = (base / name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as e:
        raise ValueError("Path escape") from e
    if not path.is_dir():
        raise FileNotFoundError("Site folder not found")
    return path
