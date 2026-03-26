from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def fill_content(
    rng: random.Random,
    brand: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    industries = _load_yaml(data_dir / "industries.yaml")
    services = _load_yaml(data_dir / "services.yaml")
    industry = rng.choice(industries) if industries else "technology"
    service = rng.choice(services) if services else "digital marketing"
    name = brand.get("brand_name", "Brand")
    return {
        "hero_title": f"{name} helps teams win in {industry}",
        "hero_subtitle": f"We provide {service} solutions tailored to your goals.",
        "about_page_header": "About us",
        "about_page_sub": "Background, values, and how we work.",
        "contact_page_header": "Contact",
        "contact_page_sub": "We respond within one business day.",
        "about_heading": "Who we are",
        "about_body": (
            f"{name} is a focused team combining strategy and execution. "
            f"We partner with organizations in {industry} to ship work that lasts."
        ),
        "services_heading": "What we do",
        "services_intro": f"Our core offerings center on {service} and related capabilities.",
        "service_items": [
            {"title": "Strategy", "text": "Roadmaps, positioning, and prioritization."},
            {"title": "Delivery", "text": "Hands-on execution with clear milestones."},
            {"title": "Support", "text": "Ongoing optimization and reporting."},
        ],
        "contact_teaser": "Tell us about your project — we reply within one business day.",
        "industry": industry,
        "service": service,
    }
