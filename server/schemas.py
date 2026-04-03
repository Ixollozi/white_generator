from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BrandOptions(BaseModel):
    domain_mode: str = Field(default="none", description="none|brand_tld|random_tld|custom")
    tlds: list[str] = Field(default_factory=lambda: ["com", "net", "org"])
    custom_domain: str | None = Field(default=None, description="Used when domain_mode=custom")
    geo_profile_id: str | None = Field(
        default=None,
        description="Bundled locale preset: en|fr|es (language, currency, topic seeds, legal/newsroom locale)",
    )
    geo_profile: dict[str, Any] | None = Field(
        default=None,
        description="Optional overrides merged into geo_profile (language, currency_code, topic_seeds, …)",
    )


class SeoOptions(BaseModel):
    generate_sitemap: bool = True
    generate_robots: bool = True
    generate_keywords: bool = False


class NoiseOptions(BaseModel):
    extra_css_max: int = Field(default=3, ge=0, le=50)
    extra_js_max: int = Field(default=3, ge=0, le=50)
    junk_pages: list[str] | None = None
    attach_assets: bool = False
    randomize_classes: bool = False
    randomize_ids: bool = False


class ImagesOptions(BaseModel):
    mode: str = Field(default="none", description="none|web|upload")
    image_source: str | None = Field(
        default=None,
        description="picsum|placeholder|unsplash|wikimedia|pack — hero/post visuals (Unsplash needs UNSPLASH_ACCESS_KEY)",
    )
    web_sources: list[str] = Field(default_factory=list)
    asset_pack_id: str | None = None
    count: int = Field(default=3, ge=0, le=30)


class IntegrationsOptions(BaseModel):
    offer_link: str = ""


class AssetPackCreated(BaseModel):
    asset_pack_id: str
    files: int


class AssetPackSummary(BaseModel):
    asset_pack_id: str
    files: int


class AssetPackFile(BaseModel):
    name: str
    url: str


class AssetPackDetails(BaseModel):
    asset_pack_id: str
    files: list[AssetPackFile]


class VerticalInfo(BaseModel):
    id: str
    label_ru: str
    hint: str | None = None


class GenerateRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=500)
    templates: list[str] = Field(default_factory=lambda: ["corporate_v1"])
    pages: list[str] | None = None
    base_url: str = "https://example.com"
    output_dir: str | None = Field(default=None, description="Subdirectory under project root, default output")
    site_name: str | None = Field(default=None, description="Custom output folder name for generated site(s)")
    vertical: str | None = Field(default=None, description="Niche id from /api/verticals; omit for random")
    theme: str = "default"
    seed: int | None = None
    strict_components: bool = False
    coherence_strict: bool = Field(
        default=False,
        description="Abort generation if brand/domain conflicts with vertical_id or service copy",
    )
    brand: BrandOptions | None = None
    seo: SeoOptions | None = None
    noise: NoiseOptions | None = None
    images: ImagesOptions | None = None
    integrations: IntegrationsOptions | None = None
    zip_each_site: bool = False
    write_build_manifest: bool = Field(
        default=False,
        description="Write build-manifest.json into the site folder (debug/metadata; omit for public deploy)",
    )
    news_article_count: int | None = Field(
        default=None,
        ge=1,
        le=80,
        description="News vertical: cap number of generated articles (default: full blueprint set)",
    )
    news_default_article_kind: str | None = Field(
        default=None,
        description="news|analysis|column — default article kind when style mix does not override",
    )
    news_style_mix: dict[str, str] | None = Field(
        default=None,
        description="Per-category or per-index overrides for article kind, e.g. {'Technology': 'column', '0': 'news'}",
    )


class ContactLeadIn(BaseModel):
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    message: str | None = None
    page: str | None = None
    website: str | None = None


class NewsletterLeadIn(BaseModel):
    email: str
    page: str | None = None
    website: str | None = None


class OrderLeadIn(BaseModel):
    email: str
    name: str
    address: str
    city: str
    postal: str
    notes: str | None = None
    cart: list[dict[str, Any]] | None = None
    page: str | None = None
    website: str | None = None


class LeadAccepted(BaseModel):
    ok: bool = True
    lead_id: str


class TemplateInfo(BaseModel):
    folder: str
    id: str | None = None
    display_name: str | None = None


class JobCreated(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress_done: int = 0
    progress_total: int = 0
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    result_paths: list[str] = Field(default_factory=list)


class SiteSummary(BaseModel):
    name: str
    path: str
    template_id: str | None = None
    brand_name: str | None = None
    build_id: str | None = None
    vertical_id: str | None = None
    theme_pack_folder: str | None = None
    has_zip: bool = False
