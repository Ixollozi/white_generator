const API_BASE = "";
let templatesCache: TemplateInfo[] | null = null;
let templatesInFlight: Promise<TemplateInfo[]> | null = null;

export type TemplateInfo = {
  folder: string;
  id: string | null;
  display_name: string | null;
};

export type VerticalInfo = {
  id: string;
  label_ru: string;
  hint: string | null;
};

export type GeneratePayload = {
  count: number;
  templates: string[];
  pages: string[] | null;
  base_url: string;
  site_name: string | null;
  vertical: string | null;
  theme: string;
  seed: number | null;
  strict_components: boolean;
  brand: {
    domain_mode: "none" | "brand_tld" | "random_tld" | "custom";
    tlds: string[];
    custom_domain?: string | null;
    geo_profile_id?: string | null;
    geo_profile?: Record<string, unknown> | null;
  };
  seo: { generate_sitemap: boolean; generate_robots: boolean; generate_keywords: boolean };
  noise: {
    extra_css_max: number;
    extra_js_max: number;
    junk_pages: string[] | null;
    attach_assets: boolean;
    randomize_classes: boolean;
    randomize_ids: boolean;
  };
  images: {
    mode: "none" | "web" | "upload";
    web_sources: string[];
    asset_pack_id: string | null;
    count: number;
    image_source?: string | null;
  };
  integrations: { offer_link: string };
  zip_each_site: boolean;
  write_build_manifest?: boolean;
  news_article_count?: number | null;
  news_default_article_kind?: string | null;
  news_style_mix?: Record<string, string> | null;
};

export type JobCreated = { job_id: string };

export type AssetPackCreated = { asset_pack_id: string; files: number };
export type AssetPackSummary = { asset_pack_id: string; files: number };
export type AssetPackFile = { name: string; url: string };
export type AssetPackDetails = { asset_pack_id: string; files: AssetPackFile[] };

export type JobStatus = {
  job_id: string;
  status: string;
  progress_done: number;
  progress_total: number;
  logs: string[];
  error: string | null;
  result_paths: string[];
};

export type SiteSummary = {
  name: string;
  path: string;
  template_id: string | null;
  brand_name: string | null;
  build_id: string | null;
  vertical_id: string | null;
  theme_pack_folder: string | null;
  has_zip: boolean;
};

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") return data.detail;
    if (data && Array.isArray(data.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join("; ");
    }
  } catch {
    /* ignore */
  }
  const st = res.statusText?.trim();
  if (st) return `Ошибка HTTP ${res.status}: ${st}`;
  return `Ошибка HTTP ${res.status}`;
}

export async function fetchHealth(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(await parseError(res));
}

export async function fetchTemplates(): Promise<TemplateInfo[]> {
  if (templatesCache) return templatesCache;
  if (templatesInFlight) return templatesInFlight;
  templatesInFlight = (async () => {
    const res = await fetch(`${API_BASE}/api/templates`);
    if (!res.ok) throw new Error(await parseError(res));
    const data = (await res.json()) as TemplateInfo[];
    templatesCache = data;
    return data;
  })();
  try {
    return await templatesInFlight;
  } finally {
    templatesInFlight = null;
  }
}

export async function fetchThemes(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/themes`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchVerticals(): Promise<VerticalInfo[]> {
  const res = await fetch(`${API_BASE}/api/verticals`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function startGenerate(body: GeneratePayload): Promise<JobCreated> {
  const res = await fetch(`${API_BASE}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function uploadImages(files: File[]): Promise<AssetPackCreated> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const res = await fetch(`${API_BASE}/api/images/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchImagePacks(): Promise<AssetPackSummary[]> {
  const res = await fetch(`${API_BASE}/api/images/packs`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchImagePack(assetPackId: string): Promise<AssetPackDetails> {
  const res = await fetch(`${API_BASE}/api/images/packs/${encodeURIComponent(assetPackId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteImagePack(assetPackId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/images/packs/${encodeURIComponent(assetPackId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchSites(): Promise<SiteSummary[]> {
  const res = await fetch(`${API_BASE}/api/output/sites`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteSite(siteName: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/output/sites/${encodeURIComponent(siteName)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export function zipUrl(siteName: string): string {
  return `${API_BASE}/api/output/sites/${encodeURIComponent(siteName)}/zip`;
}

export function previewUrl(siteName: string): string {
  return `${API_BASE}/api/output/sites/${encodeURIComponent(siteName)}/preview/`;
}
