from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.paths import default_output_path

_ROOT = Path(__file__).resolve().parents[1]
_UI_BUILT = (_ROOT / "server" / "static" / "index.html").is_file()


def test_api_health() -> None:
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_api_templates() -> None:
    with TestClient(app) as client:
        r = client.get("/api/templates")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        folders = {x["folder"] for x in data}
        assert "corporate_v1" in folders


def test_api_verticals() -> None:
    with TestClient(app) as client:
        r = client.get("/api/verticals")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        ids = {x["id"] for x in data}
        assert "cleaning" in ids
        assert "marketing_agency" in ids
        assert "clothing" in ids


def test_api_generate_rejects_unknown_vertical() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/api/generate",
            json={
                "count": 1,
                "templates": ["corporate_v1"],
                "vertical": "___not_a_real_vertical___",
            },
        )
        assert r.status_code == 400


def test_leads_endpoints_accept_json_and_form() -> None:
    with TestClient(app) as client:
        r1 = client.post(
            "/forms/subscribe",
            json={"email": "test@example.com", "page": "/index.php", "website": ""},
        )
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1.get("ok") is True
        assert data1.get("lead_id")

        r2 = client.post(
            "/forms/message",
            data={
                "email": "test@example.com",
                "name": "Tester",
                "message": "Hello, I want a quote for 1200 sq ft.",
                "page": "/contact.php",
                "website": "",
            },
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2.get("ok") is True
        assert data2.get("lead_id")


@pytest.mark.skipif(not _UI_BUILT, reason="Build UI: cd frontend && npm run build")
def test_root_serves_ui_when_built() -> None:
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


def test_delete_site_endpoint() -> None:
    base = default_output_path()
    name = f"tmp-delete-test-{uuid.uuid4().hex[:8]}"
    site = base / name
    zip_path = base / f"{name}.zip"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.php").write_text("<!doctype html>", encoding="utf-8")
    zip_path.write_text("zip", encoding="utf-8")
    with TestClient(app) as client:
        r = client.delete(f"/api/output/sites/{name}")
        assert r.status_code == 200
    assert not site.exists()
    assert not zip_path.exists()


def test_preview_rewrites_root_absolute_assets() -> None:
    base = default_output_path()
    name = f"tmp-preview-rewrite-{uuid.uuid4().hex[:8]}"
    site = base / name
    (site / "css").mkdir(parents=True, exist_ok=True)
    (site / "css" / "style.css").write_text("body{color:red;}", encoding="utf-8")
    (site / "index.php").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="/css/style.css"></head><body>ok</body></html>',
        encoding="utf-8",
    )
    try:
        with TestClient(app) as client:
            r = client.get(f"/api/output/sites/{name}/preview")
            assert r.status_code == 200
            assert f'/api/output/sites/{name}/preview/css/style.css' in r.text
            css = client.get(f"/api/output/sites/{name}/preview/css/style.css")
            assert css.status_code == 200
    finally:
        if site.exists():
            import shutil

            shutil.rmtree(site)


def test_preview_with_trailing_slash_keeps_relative_assets() -> None:
    base = default_output_path()
    name = f"tmp-preview-relative-{uuid.uuid4().hex[:8]}"
    site = base / name
    (site / "css").mkdir(parents=True, exist_ok=True)
    (site / "css" / "style.css").write_text("body{background:#fff;}", encoding="utf-8")
    (site / "index.php").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="css/style.css"></head><body>ok</body></html>',
        encoding="utf-8",
    )
    try:
        with TestClient(app) as client:
            r = client.get(f"/api/output/sites/{name}/preview/")
            assert r.status_code == 200
            assert 'href="css/style.css"' in r.text
            css = client.get(f"/api/output/sites/{name}/preview/css/style.css")
            assert css.status_code == 200
    finally:
        if site.exists():
            import shutil

            shutil.rmtree(site)
