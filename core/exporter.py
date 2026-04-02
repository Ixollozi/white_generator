from __future__ import annotations

import shutil
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
import re

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
    # Never ship generator metadata in the downloadable archive.
    # Keep it on disk for debugging/tests, but exclude it from export.
    exclude_names = {
        "build-manifest.json",
        ".ui-site-meta.json",
    }
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    def _parse_sitemap_lastmod() -> dict[str, date]:
        sm = site_dir / "sitemap.xml"
        if not sm.is_file():
            return {}
        txt = sm.read_text(encoding="utf-8", errors="ignore")
        # simple parse: <loc>.../path</loc> + <lastmod>YYYY-MM-DD</lastmod>
        out: dict[str, date] = {}
        for m in re.finditer(r"<loc>[^<]+(?P<path>/[^<]+)</loc>\\s*<lastmod>(?P<lm>\\d{4}-\\d{2}-\\d{2})</lastmod>", txt):
            p = m.group("path") or ""
            lm = m.group("lm") or ""
            try:
                out[p.lstrip("/")] = date.fromisoformat(lm)
            except ValueError:
                continue
        return out

    lastmods = _parse_sitemap_lastmod()
    today = date.today()
    build_id = ""
    bm = site_dir / "build-manifest.json"
    ui_meta = site_dir / ".ui-site-meta.json"
    if bm.is_file():
        try:
            import json

            data = json.loads(bm.read_text(encoding="utf-8", errors="ignore"))
            build_id = str((data or {}).get("build_id") or "")
        except Exception:
            build_id = ""
    elif ui_meta.is_file():
        try:
            import json

            data = json.loads(ui_meta.read_text(encoding="utf-8", errors="ignore"))
            build_id = str((data or {}).get("build_id") or "")
        except Exception:
            build_id = ""

    def _stable_days_offset(key: str, *, lo: int, hi: int) -> int:
        span = max(1, hi - lo + 1)
        h = abs(hash(f"{build_id}|{key}")) % span
        return lo + int(h)

    def _zip_dt_for(rel_posix: str) -> tuple[int, int, int, int, int, int]:
        # Prefer sitemap lastmod for pages that are listed.
        base_date = lastmods.get(rel_posix)
        if base_date is None:
            if rel_posix.startswith(("css/", "js/", "img/")):
                base_date = today - timedelta(days=_stable_days_offset(rel_posix, lo=7, hi=180))
            elif rel_posix.endswith((".php", ".html")):
                base_date = today - timedelta(days=_stable_days_offset(rel_posix, lo=0, hi=60))
            else:
                base_date = today - timedelta(days=_stable_days_offset(rel_posix, lo=3, hi=120))
        # Vary clock time per file (mass tools often stamp 12:00:00 — avoid that fingerprint).
        tick = abs(hash(f"{build_id}|{rel_posix}|mtime")) % 86_400
        hour = 7 + (tick // 3600) % 14  # 07–20
        minute = (tick // 60) % 60
        second = tick % 60
        dt = datetime.combine(base_date, time(hour, minute, second))
        # Zip supports 1980-2107; clamp.
        if dt.year < 1980:
            dt = dt.replace(year=1980)
        if dt.year > 2107:
            dt = dt.replace(year=2107)
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in site_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.name in exclude_names:
                continue
            arc = f.relative_to(site_dir).as_posix()
            info = zipfile.ZipInfo(arc)
            info.date_time = _zip_dt_for(arc)
            info.compress_type = zipfile.ZIP_DEFLATED
            with f.open("rb") as rf:
                zf.writestr(info, rf.read())
