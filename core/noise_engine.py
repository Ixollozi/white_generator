from __future__ import annotations

import random
import string
from pathlib import Path
from typing import Any


def _rand_token(rng: random.Random, n: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(n))


def write_noise_assets(
    site_dir: Path,
    rng: random.Random,
    noise_cfg: dict[str, Any],
    vertical_id: str | None = None,
) -> list[str]:
    """Create plausible extra css/js files up to configured max. Returns relative paths."""
    css_max = int(noise_cfg.get("extra_css_max") or 0)
    js_max = int(noise_cfg.get("extra_js_max") or 0)
    written: list[str] = []
    css_dir = site_dir / "css"
    js_dir = site_dir / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    for i in range(css_max):
        name = f"styles-supplement-{i + 1:02d}.css"
        p = css_dir / name
        tok = _rand_token(rng, 8)
        ghost = _rand_token(rng, 5)
        lines = [
            f"/* {tok} */",
            f":root{{--u{i}:{rng.randint(1, 99)};--v{ghost}:{rng.random():.3f}}}",
            f".g-{ghost}{{contain:layout}}",
            f"@media (prefers-reduced-motion: reduce){{.a-{tok[:4]}-{i}{{animation:none!important;transition:none!important}}}}",
            ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}",
        ]
        rng.shuffle(lines[1:-1])
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(f"css/{name}")

    vid = (vertical_id or "").strip()
    js_templates: list[str] = []

    base_helpers = [
        "/* helpers: dom */\n"
        "function $(sel, root){return (root||document).querySelector(sel)}\n"
        "function $all(sel, root){return Array.from((root||document).querySelectorAll(sel))}\n"
        "function on(el, ev, fn, opts){ if(el) el.addEventListener(ev, fn, opts||false) }\n"
        "window.SiteHelpers = window.SiteHelpers || { $, $all, on };\n",
        "/* helpers: cookies + flags */\n"
        "function getCookie(name){\n"
        "  const m = document.cookie.match(new RegExp('(?:^|; )'+name.replace(/([.$?*|{}()\\[\\]\\\\\\/\\+^])/g,'\\\\$1')+'=([^;]*)'));\n"
        "  return m ? decodeURIComponent(m[1]) : '';\n"
        "}\n"
        "function setCookie(name, val, days){\n"
        "  const d = new Date(); d.setTime(d.getTime() + (days||30)*24*60*60*1000);\n"
        "  document.cookie = name+'='+encodeURIComponent(val)+'; path=/; expires='+d.toUTCString()+'; SameSite=Lax';\n"
        "}\n"
        "window.SiteFlags = window.SiteFlags || { getCookie, setCookie };\n",
        "/* helpers: analytics queue (no-op by default) */\n"
        "window.dataLayer = window.dataLayer || [];\n"
        "function track(event, props){\n"
        "  try{ window.dataLayer.push({ event, ...(props||{}) }); }catch(e){}\n"
        "}\n"
        "window.SiteAnalytics = window.SiteAnalytics || { track };\n",
        "/* helpers: perf marks */\n"
        "function mark(name){ try{ performance && performance.mark && performance.mark(name) }catch(e){} }\n"
        "function measure(name, a, b){ try{ performance && performance.measure && performance.measure(name, a, b) }catch(e){} }\n"
        "window.SitePerf = window.SitePerf || { mark, measure };\n",
    ]

    clothing_helpers = [
        "/* clothing: size helper */\n"
        "window.SizeHelper = window.SizeHelper || {\n"
        "  toCm: function(inches){ return Math.round((inches||0) * 2.54); },\n"
        "  fromCm: function(cm){ return Math.round((cm||0) / 2.54); }\n"
        "};\n",
    ]

    restaurant_helpers = [
        "/* restaurant: opening status */\n"
        "window.ServiceHours = window.ServiceHours || {\n"
        "  isOpenNow: function(){ try{ var h=new Date().getHours(); return h>=11 && h<22; }catch(e){ return false; } }\n"
        "};\n",
    ]

    js_templates.extend(base_helpers)
    if vid == "clothing":
        js_templates.extend(clothing_helpers)
    if vid == "cafe_restaurant":
        js_templates.extend(restaurant_helpers)

    used_js_indices: set[int] = set()
    shuffled_js = list(range(len(js_templates)))
    rng.shuffle(shuffled_js)
    for i in range(min(js_max, len(js_templates))):
        name = f"app-helpers-{i + 1:02d}.js"
        p = js_dir / name
        idx = shuffled_js[i]
        used_js_indices.add(idx)
        p.write_text(
            js_templates[idx],
            encoding="utf-8",
        )
        written.append(f"js/{name}")

    written.extend(write_layout_css_bundle(site_dir))
    return written


def write_layout_css_bundle(site_dir: Path) -> list[str]:
    """Stable-named secondary stylesheets (read as generic bundles, not random hashes)."""
    css_dir = site_dir / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    # Keep these bundles non-trivial so archives don't look like placeholders.
    core = (
        "/* core */\n"
        ":root{--bundle:1;--radius:12px;--fg:#0f172a;--muted:#64748b;--bg:#ffffff;--border:#e5e7eb;}\n"
        "*,*::before,*::after{box-sizing:border-box}\n"
        "html{line-height:1.5;-webkit-text-size-adjust:100%}\n"
        "body{margin:0;color:var(--fg);background:var(--bg)}\n"
        "a{color:inherit}\n"
        "img{max-width:100%;height:auto}\n"
        ".container{max-width:1120px;margin:0 auto;padding:0 16px}\n"
        ".btn{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;padding:.55rem .9rem;border-radius:10px;border:1px solid var(--border);background:#0f172a;color:#fff;text-decoration:none}\n"
        ".card{border:1px solid var(--border);border-radius:var(--radius);background:#fff;padding:1rem}\n"
        ".muted{color:var(--muted)}\n"
        ".grid{display:grid;gap:1rem}\n"
        "@media (min-width:900px){.grid.three{grid-template-columns:repeat(3,1fr)}}\n"
        ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
    )
    layout = (
        "/* layout */\n"
        ".site-header{position:sticky;top:0;background:rgba(255,255,255,.92);backdrop-filter:saturate(180%) blur(10px);border-bottom:1px solid var(--border);z-index:10}\n"
        ".header-inner{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.5rem 0}\n"
        ".logo{display:inline-flex;align-items:center;font-weight:800;text-decoration:none;color:inherit}\n"
        ".logo img{height:36px;width:auto;display:block}\n"
        ".nav{display:flex;flex-wrap:wrap;gap:.8rem;align-items:center}\n"
        ".site-main{min-height:40vh}\n"
        ".block{padding:2rem 0}\n"
        ".footer{border-top:1px solid var(--border)}\n"
        ".footer-row{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between}\n"
    )
    vendor = (
        "/* vendor */\n"
        "/* reserved for third-party css resets/utilities */\n"
        "@supports (text-wrap: balance){h1,h2{text-wrap:balance}}\n"
    )
    files: list[tuple[str, str]] = [("core.css", core), ("layout.css", layout), ("vendor.css", vendor)]
    out: list[str] = []
    for name, body in files:
        p = css_dir / name
        p.write_text(body, encoding="utf-8")
        out.append(f"css/{name}")
    return out
