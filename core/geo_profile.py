from __future__ import annotations

from typing import Any

# Bundled presets: id is used when API/config passes only geo_profile_id.
GEO_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "en": {
        "id": "en",
        "language": "en",
        "name_locale": "en-US",
        "currency_code": "USD",
        "currency_symbol": "$",
        "legal_locale": "en",
        "topic_seeds": ["Local policy", "Regional economy", "Public data", "Verification"],
    },
    "fr": {
        "id": "fr",
        "language": "fr",
        "name_locale": "fr-FR",
        "currency_code": "EUR",
        "currency_symbol": "€",
        "legal_locale": "fr",
        "topic_seeds": ["Politique locale", "Économie régionale", "Données publiques", "Vérification"],
    },
    "es": {
        "id": "es",
        "language": "es",
        "name_locale": "es-ES",
        "currency_code": "EUR",
        "currency_symbol": "€",
        "legal_locale": "es",
        "topic_seeds": ["Política local", "Economía regional", "Datos públicos", "Verificación"],
    },
}


def resolve_geo_profile(brand_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Merge preset + optional overrides from brand config."""
    cfg = brand_cfg if isinstance(brand_cfg, dict) else {}
    raw = cfg.get("geo_profile")
    pid = str(cfg.get("geo_profile_id") or "en").strip().lower()
    base = dict(GEO_PROFILE_PRESETS.get(pid, GEO_PROFILE_PRESETS["en"]))
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is not None and v != "":
                base[k] = v
    return base


def merge_geo_into_brand(brand: dict[str, Any], brand_cfg: dict[str, Any] | None) -> dict[str, Any]:
    geo = resolve_geo_profile(brand_cfg)
    out = {**brand, "geo_profile": geo}
    lang = str(geo.get("language") or "en").strip() or "en"
    out["locale"] = lang
    return out
