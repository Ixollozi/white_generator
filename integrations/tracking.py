from __future__ import annotations

from typing import Any


def build_tracking_snippet(config: dict[str, Any]) -> str:
    """
    Keitaro / pixel placeholders — replace at deploy or via future API adapter.
    Config keys: tracking_script_url, offer_link (optional).
    """
    script = config.get("tracking_script_url") or ""
    offer = config.get("offer_link") or ""
    parts: list[str] = []
    if script:
        parts.append(
            f'<!-- tracking: set Keitaro script URL -->\n'
            f'<script defer src="{script}"></script>'
        )
    if offer:
        parts.append(f"<!-- offer_link placeholder: {offer} -->")
    return "\n".join(parts) if parts else "<!-- tracking: noop -->"
