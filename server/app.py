from __future__ import annotations

import json
import logging
import re
import shutil
import secrets
from pathlib import Path

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.exporter import zip_site_folder

from server.jobs import store
from server.paths import default_output_path, project_root, site_dir_for_name, validate_site_folder_name
from server.schemas import (
    AssetPackCreated,
    AssetPackDetails,
    AssetPackFile,
    AssetPackSummary,
    GenerateRequest,
    JobCreated,
    JobStatusResponse,
    SiteSummary,
    TemplateInfo,
)

logger = logging.getLogger("white_generator.server")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="White Generator UI API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _templates_dir() -> Path:
    return project_root() / "templates"

def _themes_dir() -> Path:
    return project_root() / "assets" / "themes"

def _asset_packs_dir() -> Path:
    return project_root() / "assets" / "asset_packs"

def _pack_dir(pack_id: str) -> Path:
    pid = re.sub(r"[^a-fA-F0-9]+", "", (pack_id or "").strip())[:64]
    if not pid:
        raise ValueError("Invalid asset pack id")
    return _asset_packs_dir() / pid

def _pack_originals(pack_id: str) -> Path:
    return _pack_dir(pack_id) / "originals"

def _safe_upload_name(name: str) -> str:
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", base)
    base = base.strip("._-")
    return base[:120] if base else "file"

def _is_allowed_image_name(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/templates", response_model=list[TemplateInfo])
def list_templates() -> list[TemplateInfo]:
    root = _templates_dir()
    if not root.is_dir():
        return []
    out: list[TemplateInfo] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / "template.yaml"
        tid: str | None = None
        dname: str | None = None
        if manifest.is_file():
            try:
                with manifest.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if isinstance(data, dict):
                    tid = data.get("id")
                    dname = data.get("display_name")
            except (OSError, yaml.YAMLError):
                pass
        out.append(TemplateInfo(folder=child.name, id=str(tid) if tid else None, display_name=str(dname) if dname else None))
    logger.info("list_templates: found=%s", len(out))
    return out


@app.get("/api/themes", response_model=list[str])
def list_themes() -> list[str]:
    root = _themes_dir()
    if not root.is_dir():
        return ["default"]
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        # A theme is considered valid if it has at least one of css/js/img directories.
        if any((child / x).is_dir() for x in ("css", "js", "img")):
            out.append(child.name)
    if not out:
        return ["default"]
    # Always show default first.
    if "default" in out:
        rest = sorted([x for x in out if x != "default"])
        return ["default", *rest]
    return sorted(out)


def _request_to_overrides(body: GenerateRequest) -> dict:
    return body.model_dump(exclude_none=True)


@app.post("/api/generate", response_model=JobCreated)
def start_generate(body: GenerateRequest) -> JobCreated:
    if not body.templates:
        raise HTTPException(status_code=400, detail="Select at least one template")
    job = store.create()
    payload = _request_to_overrides(body)
    logger.info(
        "start_generate: job_id=%s count=%s templates=%s site_name=%s",
        job.job_id,
        payload.get("count"),
        payload.get("templates"),
        payload.get("site_name"),
    )
    store.run_generate(job, payload)
    return JobCreated(job_id=job.job_id)


@app.post("/api/images/upload", response_model=AssetPackCreated)
async def upload_images(files: list[UploadFile] = File(...)) -> AssetPackCreated:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    pack_id = secrets.token_hex(8)
    root = _asset_packs_dir() / pack_id / "originals"
    root.mkdir(parents=True, exist_ok=True)
    saved = 0
    for f in files:
        safe = _safe_upload_name(f.filename or "")
        if not _is_allowed_image_name(safe):
            continue
        target = root / safe
        # avoid collisions
        if target.exists():
            stem = target.stem
            suf = target.suffix
            i = 2
            while (root / f"{stem}_{i}{suf}").exists():
                i += 1
            target = root / f"{stem}_{i}{suf}"
        data = await f.read()
        if not data:
            continue
        target.write_bytes(data)
        saved += 1
    if saved == 0:
        shutil.rmtree(_asset_packs_dir() / pack_id, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No valid image files (png/jpg/jpeg/webp/gif)")
    logger.info("upload_images: pack=%s files=%s", pack_id, saved)
    return AssetPackCreated(asset_pack_id=pack_id, files=saved)


@app.get("/api/images/packs", response_model=list[AssetPackSummary])
def list_image_packs() -> list[AssetPackSummary]:
    base = _asset_packs_dir()
    if not base.is_dir():
        return []
    out: list[AssetPackSummary] = []
    for child in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        pack_id = child.name
        originals = child / "originals"
        if not originals.is_dir():
            continue
        files = [p for p in originals.iterdir() if p.is_file() and _is_allowed_image_name(p.name)]
        out.append(AssetPackSummary(asset_pack_id=pack_id, files=len(files)))
    return out


@app.get("/api/images/packs/{asset_pack_id}", response_model=AssetPackDetails)
def get_image_pack(asset_pack_id: str) -> AssetPackDetails:
    try:
        originals = _pack_originals(asset_pack_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not originals.is_dir():
        raise HTTPException(status_code=404, detail="Asset pack not found")
    items: list[AssetPackFile] = []
    for p in sorted(originals.iterdir()):
        if not p.is_file() or not _is_allowed_image_name(p.name):
            continue
        items.append(
            AssetPackFile(
                name=p.name,
                url=f"/api/images/packs/{asset_pack_id}/files/{p.name}",
            )
        )
    return AssetPackDetails(asset_pack_id=asset_pack_id, files=items)


@app.get("/api/images/packs/{asset_pack_id}/files/{file_name}")
def get_image_pack_file(asset_pack_id: str, file_name: str) -> FileResponse:
    try:
        originals = _pack_originals(asset_pack_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not originals.is_dir():
        raise HTTPException(status_code=404, detail="Asset pack not found")
    safe = _safe_upload_name(file_name)
    if not _is_allowed_image_name(safe):
        raise HTTPException(status_code=400, detail="Invalid image name")
    target = (originals / safe).resolve()
    if not str(target).startswith(str(originals.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target))


@app.delete("/api/images/packs/{asset_pack_id}")
def delete_image_pack(asset_pack_id: str) -> dict[str, str]:
    try:
        pack_dir = _pack_dir(asset_pack_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not pack_dir.is_dir():
        raise HTTPException(status_code=404, detail="Asset pack not found")
    shutil.rmtree(pack_dir, ignore_errors=True)
    return {"status": "ok"}


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str) -> JobStatusResponse:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    response = JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        logs=job.logs,
        error=job.error,
        result_paths=job.result_paths,
    )
    logger.debug(
        "job_status: job_id=%s status=%s progress=%s/%s",
        job_id,
        response.status,
        response.progress_done,
        response.progress_total,
    )
    return response


@app.get("/api/runs")
def list_runs() -> JSONResponse:
    return JSONResponse(store.list_history())


def _output_base() -> Path:
    return default_output_path()


def _resolve_site_file(site_name: str, file_path: str) -> Path:
    try:
        validate_site_folder_name(site_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    base = _output_base()
    folder = site_dir_for_name(site_name, base)
    target = (folder / file_path).resolve()
    if not str(target).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if target.is_dir():
        for idx in ("index.php", "index.html"):
            cand = target / idx
            if cand.is_file():
                return cand
        raise HTTPException(status_code=404, detail="Directory index not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


def _render_preview_html(site_name: str, target: Path) -> HTMLResponse:
    text = target.read_text(encoding="utf-8", errors="ignore")
    prefix = f"/api/output/sites/{site_name}/preview/"
    # Rewrite root-absolute asset URLs for preview context.
    text = re.sub(
        r"""(?P<attr>\b(?:href|src|action)\s*=\s*["'])/(?P<rest>(?!/)[^"']*)""",
        lambda m: f"{m.group('attr')}{prefix}{m.group('rest')}",
        text,
        flags=re.IGNORECASE,
    )
    # Rewrite CSS url(/...) references inside inline styles.
    text = re.sub(
        r"""url\((?P<q>["']?)/(?P<rest>(?!/)[^)\"']+)(?P=q)\)""",
        lambda m: f"url({m.group('q')}{prefix}{m.group('rest')}{m.group('q')})",
        text,
        flags=re.IGNORECASE,
    )
    return HTMLResponse(content=text)


@app.get("/api/output/sites", response_model=list[SiteSummary])
def list_sites() -> list[SiteSummary]:
    base = _output_base()
    if not base.is_dir():
        return []
    items: list[SiteSummary] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "build-manifest.json"
        template_id = None
        brand_name = None
        build_id = None
        if manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    template_id = data.get("template_id")
                    brand_name = data.get("brand_name")
                    build_id = data.get("build_id")
            except (OSError, json.JSONDecodeError):
                pass
        zip_path = child.with_suffix(".zip")
        items.append(
            SiteSummary(
                name=child.name,
                path=str(child.resolve()),
                template_id=str(template_id) if template_id else None,
                brand_name=str(brand_name) if brand_name else None,
                build_id=str(build_id) if build_id else None,
                has_zip=zip_path.is_file(),
            )
        )
    logger.info("list_sites: found=%s", len(items))
    return items


@app.delete("/api/output/sites/{site_name}")
def delete_site(site_name: str) -> dict[str, str]:
    try:
        validate_site_folder_name(site_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    base = _output_base()
    folder = site_dir_for_name(site_name, base)
    zip_path = folder.with_suffix(".zip")
    try:
        shutil.rmtree(folder)
        if zip_path.is_file():
            zip_path.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not delete site: {e}") from e
    logger.info("delete_site: removed site=%s", site_name)
    return {"status": "ok"}


@app.get("/api/output/sites/{site_name}/preview")
@app.get("/api/output/sites/{site_name}/preview/")
def preview_site_root(site_name: str) -> HTMLResponse:
    logger.info("preview_site_root: site=%s", site_name)
    for entry in ("index.php", "index.html"):
        try:
            target = _resolve_site_file(site_name, entry)
            logger.info("preview_site_root: site=%s entry=%s", site_name, target.name)
            return _render_preview_html(site_name, target)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            continue
    raise HTTPException(status_code=404, detail="Preview entry page not found")


@app.get("/api/output/sites/{site_name}/preview/{file_path:path}")
def preview_site_file(site_name: str, file_path: str) -> FileResponse:
    target = _resolve_site_file(site_name, file_path)
    logger.debug("preview_site_file: site=%s file=%s", site_name, file_path)
    suffix = target.suffix.lower()
    media_type = None
    # Generated ".php" files are static HTML wrappers; serve as HTML for visual preview.
    if suffix in {".php", ".html", ".htm"}:
        return _render_preview_html(site_name, target)
    return FileResponse(path=str(target), media_type=media_type)


@app.get("/api/output/sites/{site_name}/zip")
def download_site_zip(site_name: str) -> FileResponse:
    try:
        validate_site_folder_name(site_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    base = _output_base()
    folder = site_dir_for_name(site_name, base)
    zip_path = folder.with_suffix(".zip")
    if not zip_path.is_file():
        zip_site_folder(folder, zip_path)
    if not zip_path.is_file():
        raise HTTPException(status_code=500, detail="Could not create zip")
    logger.info("download_site_zip: site=%s zip=%s", site_name, zip_path.name)
    return FileResponse(
        path=str(zip_path),
        filename=f"{site_name}.zip",
        media_type="application/zip",
    )


_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir() and (_static_dir / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
