from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any

from jinja2 import Environment


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def copy_theme_assets(assets_root: Path, theme: str, site_dir: Path) -> None:
    theme_dir = assets_root / "themes" / theme
    _copy_tree(theme_dir / "css", site_dir / "css")
    _copy_tree(theme_dir / "js", site_dir / "js")
    _copy_tree(theme_dir / "img", site_dir / "img")


def copy_template_static(template_dir: Path, site_dir: Path) -> None:
    static_dir = template_dir / "static"
    _copy_tree(static_dir / "css", site_dir / "css")
    _copy_tree(static_dir / "js", site_dir / "js")
    _copy_tree(static_dir / "img", site_dir / "img")


def write_htaccess(site_dir: Path) -> None:
    content = (
        "Options -Indexes\n"
        "DirectoryIndex index.php\n"
        "ErrorDocument 404 /404.php\n"
    )
    (site_dir / ".htaccess").write_text(content, encoding="utf-8")


def render_junk_page(
    env: Environment,
    template_name: str,
    variables: dict[str, Any],
) -> str:
    return env.get_template(template_name).render(**variables)


def zip_site_folder(site_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in site_dir.rglob("*"):
            if f.is_file():
                arc = f.relative_to(site_dir)
                zf.write(f, arc.as_posix())
