from __future__ import annotations

import hashlib
import random
import re
from typing import Any

# Human-readable namespace tokens (not hex fingerprints) for optional class/id prefixes.
_CLASS_LEX: tuple[str, ...] = (
    "stack",
    "shell",
    "frame",
    "wrap",
    "layer",
    "slot",
    "grid",
    "flow",
    "band",
    "rail",
    "pane",
    "sheet",
    "block",
    "cell",
    "cluster",
)

_ID_LEX: tuple[str, ...] = (
    "main",
    "sub",
    "top",
    "base",
    "side",
    "core",
    "focus",
    "anchor",
    "region",
    "panel",
    "aside",
    "note",
)


def compute_class_prefix(chunk: str, mode: str, rng: random.Random) -> str:
    """Deterministic decorative class prefix (same inputs as used when randomize_classes is on)."""
    raw = hashlib.sha256(f"class|{chunk}|{mode}".encode()).hexdigest()
    i = int(raw[:12], 16)
    a = _CLASS_LEX[i % len(_CLASS_LEX)]
    b = _CLASS_LEX[(i // 17) % len(_CLASS_LEX)]
    n = 10 + (i % 80)
    mode_n = (mode or "").strip().lower()
    if mode_n == "short":
        return f"{a}-{n}"
    if mode_n == "bem":
        return f"block-{a}__{b}"
    return f"{a}-{b}"


def strip_decoy_class_prefix(html: str, prefix: str) -> str:
    """Remove a known generator class prefix from every class attribute (e.g. stack-70)."""
    p = (prefix or "").strip()
    if not p:
        return html
    pref = re.escape(p) + r"\s+"

    def _strip_class(m: re.Match[str]) -> str:
        inner = (m.group(1) or "").strip()
        rest = re.sub(rf"^{pref}", "", inner, count=1).strip()
        if not rest:
            return ""
        return f'class="{rest}"'

    out = re.sub(r'class="([^"]*)"', _strip_class, html)
    out = re.sub(r'\s+class="\s*"', "", out)
    return out


def _id_prefix_from_token(chunk: str) -> str:
    raw = hashlib.sha256(f"id|{chunk}".encode()).hexdigest()
    i = int(raw[:12], 16)
    a = _ID_LEX[i % len(_ID_LEX)]
    b = _ID_LEX[(i // 19) % len(_ID_LEX)]
    return f"{a}-{b}"


def apply_html_noise(html: str, rng: random.Random, noise_cfg: dict[str, Any], token: str) -> str:
    """
    Optional class/id decoration for generated HTML.
    Prefixes href="#fragment" when id values are prefixed so in-page links stay valid.
    When strip_class_prefix is true (default), removes the decorative class prefix after injection
    so templates keep stable CSS hooks without leaking generator tokens in the export.
    """
    out = html
    class_tok = ""
    if bool(noise_cfg.get("randomize_classes")):
        chunk = (token or "").strip().lower()
        if not chunk:
            chunk = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))
        mode = str(noise_cfg.get("class_prefix_mode") or "").strip().lower()
        if not mode:
            mode = rng.choice(["std", "short", "bem"])
        class_tok = compute_class_prefix(chunk, mode, rng)

        def _cls(m: re.Match[str]) -> str:
            inner = (m.group(1) or "").strip()
            if not inner:
                return m.group(0)
            return f'class="{class_tok} {inner}"'

        out = re.sub(r'class="([^"]*)"', _cls, out)

    if bool(noise_cfg.get("randomize_ids")):
        chunk = (token or "").strip().lower()
        if not chunk:
            chunk = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))
        id_prefix = _id_prefix_from_token(chunk)
        keep_ids = set(str(x) for x in (noise_cfg.get("id_safelist") or []))
        keep_ids.update(
            {
                "cookie-consent",
                "cookie-ok",
            }
        )

        def _id(m: re.Match[str]) -> str:
            val = (m.group(1) or "").strip()
            if not val or val in keep_ids or val.startswith(f"{id_prefix}-"):
                return m.group(0)
            return f'id="{id_prefix}-{val}"'

        out = re.sub(r'id="([^"]*)"', _id, out)

        def _href_hash(m: re.Match[str]) -> str:
            frag = m.group(1) or ""
            if not frag or frag.startswith(f"{id_prefix}-") or frag.startswith("http"):
                return m.group(0)
            return f'href="#{id_prefix}-{frag}"'

        out = re.sub(r'href="#([^"]*)"', _href_hash, out)

    if class_tok and bool(noise_cfg.get("strip_class_prefix", True)):
        out = strip_decoy_class_prefix(out, class_tok)

    return out
