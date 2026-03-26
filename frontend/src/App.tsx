import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteSite,
  deleteImagePack,
  fetchJob,
  fetchImagePack,
  fetchImagePacks,
  fetchSites,
  fetchTemplates,
  fetchThemes,
  previewUrl,
  startGenerate,
  uploadImages,
  zipUrl,
  type GeneratePayload,
  type JobStatus,
  type AssetPackDetails,
  type AssetPackSummary,
  type SiteSummary,
  type TemplateInfo,
} from "./api";

type Tab = "generate" | "outputs" | "history";

const JUNK_OPTIONS = [
  "privacy-policy",
  "terms-of-service",
  "cookie-policy",
];

const JUNK_LABELS: Record<string, string> = {
  "privacy-policy": "Политика конфиденциальности",
  "terms-of-service": "Условия использования",
  "cookie-policy": "Политика cookie",
};

const JUNK_HINTS: Record<string, string> = {
  "privacy-policy": "Добавит отдельную страницу «Политика конфиденциальности». Нужна почти на любом сайте, чтобы было понятно, как обрабатываются данные.",
  "terms-of-service": "Добавит страницу «Условия использования». Это правила пользования сайтом (часто требуется для юридической чистоты).",
  "cookie-policy": "Добавит страницу про cookie (файлы, которые сайт может сохранять в браузере). Часто требуется для соответствия правилам/проверкам.",
};

const JOB_STATUS_RU: Record<string, string> = {
  queued: "в очереди",
  running: "выполняется",
  done: "готово",
  error: "ошибка",
};

function jobStatusRu(status: string): string {
  return JOB_STATUS_RU[status] ?? status;
}

function templateHint(folder: string, label?: string | null): string {
  const key = (folder || "").toLowerCase();
  if (key.includes("reference"))
    return "Это демонстрационный шаблон-пример. Подходит, чтобы посмотреть, как выглядит структура сайта и как работают блоки.";
  if (key.includes("corporate"))
    return "Обычный «корпоративный» шаблон. Подойдёт для большинства ниш: главная, о нас, услуги, контакты.";
  if (key.includes("minimal"))
    return "Очень простой шаблон без лишнего. Подойдёт, если нужен максимально лёгкий и быстрый вариант.";
  return label ? `Шаблон: ${label}. Выберите, если хотите сгенерировать сайт в этом стиле.` : "Выберите шаблон — это внешний вид и структура будущего сайта.";
}

export default function App() {
  const [tab, setTab] = useState<Tab>("generate");
  const [toast, setToast] = useState<string | null>(null);
  const [toastErr, setToastErr] = useState(false);

  const showToast = (msg: string, isErr = false) => {
    setToast(msg);
    setToastErr(isErr);
    window.setTimeout(() => setToast(null), 4200);
  };

  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [themes, setThemes] = useState<string[]>([]);
  const [selectedTemplates, setSelectedTemplates] = useState<Set<string>>(new Set(["corporate_v1"]));
  const [count, setCount] = useState(1);
  const [baseUrl, setBaseUrl] = useState("https://example.com");
  const [seed, setSeed] = useState<string>("");
  const [theme, setTheme] = useState("default");
  const [siteName, setSiteName] = useState("");
  const [strict, setStrict] = useState(false);
  const [zipEach, setZipEach] = useState(false);
  const [seoSitemap, setSeoSitemap] = useState(true);
  const [seoRobots, setSeoRobots] = useState(true);
  const [seoKeywords, setSeoKeywords] = useState(false);
  const [domainMode, setDomainMode] = useState<"none" | "brand_tld" | "random_tld" | "custom">("none");
  const [customDomain, setCustomDomain] = useState("");
  const [noiseCss, setNoiseCss] = useState(3);
  const [noiseJs, setNoiseJs] = useState(3);
  const [noiseAttachAssets, setNoiseAttachAssets] = useState(false);
  const [noiseRandomizeClasses, setNoiseRandomizeClasses] = useState(false);
  const [noiseRandomizeIds, setNoiseRandomizeIds] = useState(false);
  const [junk, setJunk] = useState<Set<string>>(new Set(JUNK_OPTIONS));
  const [imagesMode, setImagesMode] = useState<"none" | "web" | "upload">("none");
  const [imagesCount, setImagesCount] = useState(3);
  const [imagesWebSources, setImagesWebSources] = useState<string>("");
  const [imagesAssetPackId, setImagesAssetPackId] = useState<string>("");
  const [imagesUploadFiles, setImagesUploadFiles] = useState<File[]>([]);
  const [imagesUploading, setImagesUploading] = useState(false);
  const [imagePacks, setImagePacks] = useState<AssetPackSummary[]>([]);
  const [imagePacksLoading, setImagePacksLoading] = useState(false);
  const [activePack, setActivePack] = useState<AssetPackDetails | null>(null);
  const [activePackLoading, setActivePackLoading] = useState(false);
  const [offerLink, setOfferLink] = useState("");

  const [job, setJob] = useState<JobStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [history, setHistory] = useState<unknown[]>([]);

  const loadTemplates = useCallback(async () => {
    try {
      const t = await fetchTemplates();
      setTemplates(t);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось загрузить шаблоны", true);
    }
  }, []);

  const loadThemes = useCallback(async () => {
    try {
      const t0 = await fetchThemes();
      const t = t0.includes("default") ? ["default", ...t0.filter((x) => x !== "default")] : t0;
      setThemes(t);
      if (t.length > 0 && !t.includes(theme)) setTheme(t[0]);
    } catch (e) {
      // If themes can't be loaded, keep manual theme value.
      setThemes(["default"]);
    }
  }, [theme]);

  const loadSites = useCallback(async () => {
    try {
      setSites(await fetchSites());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось получить список сайтов", true);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/runs");
      if (!res.ok) throw new Error(await res.text());
      setHistory(await res.json());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось загрузить историю", true);
    }
  }, []);

  const loadImagePacks = useCallback(async () => {
    setImagePacksLoading(true);
    try {
      setImagePacks(await fetchImagePacks());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось загрузить список картинок", true);
    } finally {
      setImagePacksLoading(false);
    }
  }, []);

  const openPack = async (packId: string) => {
    setActivePackLoading(true);
    try {
      setActivePack(await fetchImagePack(packId));
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось открыть набор", true);
    } finally {
      setActivePackLoading(false);
    }
  };

  const removePack = async (packId: string) => {
    if (!window.confirm(`Удалить набор картинок "${packId}"?`)) return;
    try {
      await deleteImagePack(packId);
      if (imagesAssetPackId.trim() === packId) setImagesAssetPackId("");
      if (activePack?.asset_pack_id === packId) setActivePack(null);
      void loadImagePacks();
      showToast("Набор удален");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось удалить набор", true);
    }
  };

  useEffect(() => {
    void loadTemplates();
    void loadThemes();
  }, [loadTemplates, loadThemes]);

  useEffect(() => {
    if (tab === "outputs") void loadSites();
    if (tab === "history") void loadHistory();
  }, [tab, loadSites, loadHistory]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const id = window.setInterval(async () => {
      try {
        const j = await fetchJob(job.job_id);
        setJob(j);
        if (j.status === "done") {
          showToast("Генерация завершена");
          void loadSites();
        }
        if (j.status === "error") showToast(j.error || "Ошибка генерации", true);
      } catch (e) {
        showToast(e instanceof Error ? e.message : "Ошибка опроса задачи", true);
      }
    }, 600);
    return () => window.clearInterval(id);
  }, [job?.job_id, job?.status, loadSites]);

  const toggleTemplate = (folder: string) => {
    setSelectedTemplates((prev) => {
      const n = new Set(prev);
      if (n.has(folder)) n.delete(folder);
      else n.add(folder);
      return n;
    });
  };

  const toggleJunk = (key: string) => {
    setJunk((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  };

  const payload: GeneratePayload = useMemo(
    () => ({
      count,
      templates: Array.from(selectedTemplates),
      pages: null,
      base_url: baseUrl,
      site_name: siteName.trim() ? siteName.trim() : null,
      theme,
      seed: seed.trim() === "" ? null : Number(seed),
      strict_components: strict,
      brand: {
        domain_mode: domainMode,
        tlds: ["com", "net", "org"],
        custom_domain: domainMode === "custom" ? (customDomain.trim() ? customDomain.trim() : null) : null,
      },
      seo: { generate_sitemap: seoSitemap, generate_robots: seoRobots, generate_keywords: seoKeywords },
      noise: {
        extra_css_max: noiseCss,
        extra_js_max: noiseJs,
        junk_pages: junk.size ? Array.from(junk) : null,
        attach_assets: noiseAttachAssets,
        randomize_classes: noiseRandomizeClasses,
        randomize_ids: noiseRandomizeIds,
      },
      images: {
        mode: imagesMode,
        web_sources: imagesWebSources
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        asset_pack_id: imagesAssetPackId.trim() ? imagesAssetPackId.trim() : null,
        count: imagesMode === "upload" ? 0 : imagesCount,
      },
      integrations: { offer_link: offerLink },
      zip_each_site: zipEach,
    }),
    [
      count,
      selectedTemplates,
      baseUrl,
      siteName,
      theme,
      seed,
      strict,
      seoSitemap,
      seoRobots,
      seoKeywords,
      domainMode,
      customDomain,
      noiseCss,
      noiseJs,
      noiseAttachAssets,
      noiseRandomizeClasses,
      noiseRandomizeIds,
      junk,
      imagesMode,
      imagesCount,
      imagesWebSources,
      imagesAssetPackId,
      imagesUploadFiles,
      offerLink,
      zipEach,
    ]
  );

  const onUploadImages = async () => {
    if (imagesUploadFiles.length === 0) {
      showToast("Выберите файлы", true);
      return;
    }
    setImagesUploading(true);
    try {
      const res = await uploadImages(imagesUploadFiles);
      setImagesAssetPackId(res.asset_pack_id);
      showToast(`Загружено файлов: ${res.files}`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось загрузить изображения", true);
    } finally {
      setImagesUploading(false);
    }
  };

  const onSubmit = async () => {
    if (selectedTemplates.size === 0) {
      showToast("Выберите хотя бы один шаблон", true);
      return;
    }
    setSubmitting(true);
    try {
      const { job_id } = await startGenerate(payload);
      const initial = await fetchJob(job_id);
      setJob(initial);
      showToast("Задача запущена");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось запустить", true);
    } finally {
      setSubmitting(false);
    }
  };

  const progressPct =
    job && job.progress_total > 0
      ? Math.min(100, Math.round((job.progress_done / job.progress_total) * 100))
      : 0;

  const recentSiteNames = useMemo(() => {
    if (!job || job.status !== "done") return [];
    return job.result_paths
      .map((p) => p.replace(/\\/g, "/").split("/").filter(Boolean).pop() || "")
      .filter((x) => x.length > 0);
  }, [job]);

  const firstRecentSite = recentSiteNames[0] || null;

  const copyPath = async (p: string) => {
    try {
      await navigator.clipboard.writeText(p);
      showToast("Путь скопирован");
    } catch {
      showToast("Не удалось скопировать путь", true);
    }
  };

  const onDeleteSite = async (name: string) => {
    if (!window.confirm(`Удалить сайт "${name}"?`)) return;
    try {
      await deleteSite(name);
      setSites((prev) => prev.filter((s) => s.name !== name));
      showToast("Сайт удален");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось удалить сайт", true);
    }
  };

  return (
    <div className="app-shell">
      <header className="hero">
        <h1>Генератор вайтов</h1>
        <p>
          Пакетная сборка PHP-лендингов из шаблонов и блоков. Настройте SEO, шум и seed — архивы забирайте
          на вкладке «Результаты».
        </p>
      </header>

      <div className="tabs" role="tablist">
        <button
          type="button"
          className="tab"
          aria-selected={tab === "generate"}
          onClick={() => setTab("generate")}
        >
          Генерация
        </button>
        <button
          type="button"
          className="tab"
          aria-selected={tab === "outputs"}
          onClick={() => setTab("outputs")}
        >
          Результаты
        </button>
        <button
          type="button"
          className="tab"
          aria-selected={tab === "history"}
          onClick={() => setTab("history")}
        >
          История
        </button>
      </div>

      {tab === "generate" && (
        <>
          <section className="card">
            <h2>Шаблоны</h2>
            <div className="template-grid">
              {templates.map((t) => (
                <label
                  key={t.folder}
                  className="template-chip"
                  title={templateHint(t.folder, t.display_name || t.id || t.folder)}
                >
                  <input
                    type="checkbox"
                    checked={selectedTemplates.has(t.folder)}
                    onChange={() => toggleTemplate(t.folder)}
                  />
                  <span>{t.display_name || t.id || t.folder}</span>
                </label>
              ))}
            </div>
            {templates.length === 0 && (
              <p className="muted">В каталоге templates шаблоны не найдены.</p>
            )}
          </section>

          <section className="card">
            <h2>Основные параметры</h2>
            <div className="grid2">
              <div className="field">
                <label htmlFor="count">Количество сайтов</label>
                <input
                  id="count"
                  type="number"
                  min={1}
                  max={500}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="seed">Seed (необязательно)</label>
                <input
                  id="seed"
                  type="number"
                  placeholder="случайно для каждого"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="base">Базовый URL</label>
                <input id="base" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="theme">Тема оформления</label>
                <div className="template-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                  {(themes.length ? themes : ["default"]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      className="tab"
                      aria-selected={theme === t}
                      onClick={() => setTheme(t)}
                      title="Выберите внешний вид сайта. Меняет цвета/кнопки/фон (зависит от темы)."
                      style={{
                        justifyContent: "center",
                        opacity: theme === t ? 1 : 0.8,
                        borderColor: theme === t ? "var(--primary)" : undefined,
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <label htmlFor="site_name">Имя сайта (необязательно)</label>
                <input
                  id="site_name"
                  placeholder="например: poppycoffee"
                  value={siteName}
                  onChange={(e) => setSiteName(e.target.value)}
                />
              </div>
            </div>
            <label
              className="template-chip"
              style={{ marginTop: "0.5rem" }}
              title="Проверяет шаблон «по-строгому». Если где-то в шаблоне есть ошибка (например, используется переменная, которой нет), генерация остановится и покажет проблему. Полезно, когда вы правите шаблоны."
            >
              <input type="checkbox" checked={strict} onChange={() => setStrict((s) => !s)} />
              <span>Строгая проверка переменных компонентов</span>
            </label>
            <label
              className="template-chip"
              style={{ marginLeft: "0.5rem" }}
              title="Упаковывает каждый сгенерированный сайт в отдельный .zip, чтобы было удобно скачать и отправить."
            >
              <input type="checkbox" checked={zipEach} onChange={() => setZipEach((z) => !z)} />
              <span>Архивировать каждый сайт (zip)</span>
            </label>
          </section>

          <section className="card">
            <h2>SEO</h2>
            <label className="template-chip" title="Добавит файл sitemap.xml — это список всех страниц сайта для поисковиков (чтобы им проще было «увидеть» страницы).">
              <input type="checkbox" checked={seoSitemap} onChange={() => setSeoSitemap((v) => !v)} />
              <span>Карта сайта (sitemap)</span>
            </label>
            <label
              className="template-chip"
              style={{ marginLeft: "0.5rem" }}
              title="Добавит файл robots.txt — это «инструкция» для поисковиков. Обычно оставляют включённым."
            >
              <input type="checkbox" checked={seoRobots} onChange={() => setSeoRobots((v) => !v)} />
              <span>Файл robots.txt</span>
            </label>
            <label
              className="template-chip"
              style={{ marginLeft: "0.5rem" }}
              title="Добавит в страницы meta keywords (список ключевых слов). На современные поисковики почти не влияет, но иногда просят по ТЗ."
            >
              <input type="checkbox" checked={seoKeywords} onChange={() => setSeoKeywords((v) => !v)} />
              <span>Meta keywords</span>
            </label>
            <div className="field" style={{ marginTop: "0.75rem" }}>
              <label htmlFor="domainMode">Домен бренда</label>
              <select
                id="domainMode"
                value={domainMode}
                onChange={(e) => setDomainMode(e.target.value as typeof domainMode)}
              >
                <option value="none">не генерировать</option>
                <option value="brand_tld">brand + tld (.com/.net/.org)</option>
                <option value="random_tld">случайный домен (как email)</option>
                <option value="custom">выбрать свой домен</option>
              </select>
            </div>
            {domainMode === "custom" && (
              <div className="field" style={{ marginTop: "0.75rem" }}>
                <label htmlFor="customDomain">Свой домен</label>
                <input
                  id="customDomain"
                  placeholder="например: example.com"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                />
              </div>
            )}
          </section>

          <section className="card">
            <h2>Шум</h2>
            <div className="grid2">
              <div className="field">
                <label htmlFor="ncss">Доп. CSS-файлов (макс.)</label>
                <input
                  id="ncss"
                  type="number"
                  min={0}
                  max={50}
                  value={noiseCss}
                  onChange={(e) => setNoiseCss(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="njs">Доп. JS-файлов (макс.)</label>
                <input
                  id="njs"
                  type="number"
                  min={0}
                  max={50}
                  value={noiseJs}
                  onChange={(e) => setNoiseJs(Number(e.target.value))}
                />
              </div>
            </div>
            <p className="muted" style={{ margin: "0.5rem 0" }}>
              Служебные страницы
            </p>
            <div className="template-grid">
              {JUNK_OPTIONS.map((j) => (
                <label key={j} className="template-chip" title={JUNK_HINTS[j] ?? "Добавляет служебную страницу в сборку."}>
                  <input type="checkbox" checked={junk.has(j)} onChange={() => toggleJunk(j)} />
                  <span>{JUNK_LABELS[j] ?? j}</span>
                </label>
              ))}
            </div>
            <div style={{ marginTop: "0.75rem" }}>
              <label
                className="template-chip"
                title="Добавит на страницы дополнительные CSS/JS файлы «для шума». Это делает код менее одинаковым между сайтами."
              >
                <input
                  type="checkbox"
                  checked={noiseAttachAssets}
                  onChange={() => setNoiseAttachAssets((v) => !v)}
                />
                <span>Подключать noise css/js в HTML</span>
              </label>
              <label
                className="template-chip"
                style={{ marginLeft: "0.5rem" }}
                title="Случайно меняет названия CSS-классов в HTML (внешний вид останется, но код будет выглядеть иначе)."
              >
                <input
                  type="checkbox"
                  checked={noiseRandomizeClasses}
                  onChange={() => setNoiseRandomizeClasses((v) => !v)}
                />
                <span>Рандомизировать class</span>
              </label>
              <label
                className="template-chip"
                style={{ marginLeft: "0.5rem" }}
                title="Случайно меняет значения id в HTML (чтобы сайты меньше совпадали по коду)."
              >
                <input
                  type="checkbox"
                  checked={noiseRandomizeIds}
                  onChange={() => setNoiseRandomizeIds((v) => !v)}
                />
                <span>Рандомизировать id</span>
              </label>
            </div>
          </section>

          <section className="card">
            <h2>Изображения</h2>
            <div className="grid2">
              <div className="field">
                <label htmlFor="imgMode">Режим</label>
                <select
                  id="imgMode"
                  value={imagesMode}
                  onChange={(e) => setImagesMode(e.target.value as typeof imagesMode)}
                >
                  <option value="none">none</option>
                  <option value="web">web (скачать)</option>
                  <option value="upload">upload (свои)</option>
                </select>
              </div>
              {imagesMode !== "upload" && (
                <div className="field">
                  <label htmlFor="imgCount">Количество (макс.)</label>
                  <input
                    id="imgCount"
                    type="number"
                    min={0}
                    max={30}
                    value={imagesCount}
                    onChange={(e) => setImagesCount(Number(e.target.value))}
                  />
                </div>
              )}
              {imagesMode === "web" && (
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label htmlFor="imgSources">Источники (через запятую)</label>
                  <input
                    id="imgSources"
                    placeholder="например: https://picsum.photos"
                    value={imagesWebSources}
                    onChange={(e) => setImagesWebSources(e.target.value)}
                  />
                </div>
              )}
              {imagesMode === "upload" && (
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label htmlFor="assetPack">Asset pack id (появится после загрузки)</label>
                  <input
                    id="assetPack"
                    placeholder="пока пусто — появится после загрузки"
                    value={imagesAssetPackId}
                    onChange={(e) => setImagesAssetPackId(e.target.value)}
                  />
                  <div className="row-actions" style={{ marginTop: "0.5rem" }}>
                    <button type="button" className="btn-secondary" onClick={() => void loadImagePacks()}>
                      {imagePacksLoading ? "Обновление…" : "Мои загруженные фото"}
                    </button>
                    {imagesAssetPackId.trim() && (
                      <>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => void openPack(imagesAssetPackId.trim())}
                        >
                          Просмотреть этот набор
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => void removePack(imagesAssetPackId.trim())}
                        >
                          Удалить этот набор
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
              {imagesMode === "upload" && (
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label htmlFor="imgFiles">Файлы</label>
                  <input
                    id="imgFiles"
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={(e) => setImagesUploadFiles(Array.from(e.target.files || []))}
                  />
                  <div className="row-actions" style={{ marginTop: "0.5rem" }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={imagesUploading}
                      onClick={() => void onUploadImages()}
                    >
                      {imagesUploading ? "Загрузка…" : "Загрузить"}
                    </button>
                    {imagesUploadFiles.length > 0 && <span className="muted">выбрано: {imagesUploadFiles.length}</span>}
                  </div>
                </div>
              )}
            </div>
            <p className="muted" style={{ marginTop: "0.5rem" }}>
              В режиме upload используем все загруженные файлы из asset pack.
            </p>

            {(imagePacks.length > 0 || activePack || imagePacksLoading) && (
              <div style={{ marginTop: "0.75rem" }}>
                {imagePacks.length > 0 && (
                  <>
                    <p className="muted" style={{ margin: "0.25rem 0" }}>
                      Наборы картинок
                    </p>
                    <div className="template-grid">
                      {imagePacks.map((p) => (
                        <span
                          key={p.asset_pack_id}
                          className="template-chip"
                          style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
                          title="Это набор ваших загруженных картинок. Можно открыть для просмотра или удалить."
                        >
                          <span style={{ cursor: "pointer" }} onClick={() => void openPack(p.asset_pack_id)}>
                            {p.asset_pack_id} <span className="muted">({p.files})</span>
                          </span>
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => {
                              setImagesAssetPackId(p.asset_pack_id);
                              void openPack(p.asset_pack_id);
                            }}
                            title="Использовать этот набор для генерации"
                          >
                            Использовать
                          </button>
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => void removePack(p.asset_pack_id)}
                            title="Удалить этот набор картинок"
                          >
                            Удалить
                          </button>
                        </span>
                      ))}
                    </div>
                  </>
                )}

                {activePackLoading && <p className="muted">Загрузка превью…</p>}
                {activePack && (
                  <div style={{ marginTop: "0.75rem" }}>
                    <p className="muted" style={{ margin: "0.25rem 0" }}>
                      Просмотр набора: <strong>{activePack.asset_pack_id}</strong> (файлов: {activePack.files.length})
                    </p>
                    {activePack.files.length === 0 ? (
                      <p className="muted">В наборе нет файлов.</p>
                    ) : (
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
                          gap: "0.5rem",
                        }}
                      >
                        {activePack.files.map((f) => (
                          <a
                            key={f.url}
                            href={f.url}
                            target="_blank"
                            rel="noreferrer"
                            title={f.name}
                            style={{
                              display: "block",
                              border: "1px solid var(--border)",
                              borderRadius: 10,
                              overflow: "hidden",
                              background: "var(--card)",
                            }}
                          >
                            <img
                              src={f.url}
                              alt={f.name}
                              style={{ width: "100%", height: 110, objectFit: "cover", display: "block" }}
                              loading="lazy"
                            />
                            <div className="muted" style={{ padding: "0.35rem 0.5rem", fontSize: 12 }}>
                              {f.name}
                            </div>
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="card">
            <h2>Интеграции (заглушки)</h2>
            <div className="field">
              <label htmlFor="offer">Ссылка на оффер</label>
              <input id="offer" value={offerLink} onChange={(e) => setOfferLink(e.target.value)} />
            </div>
          </section>

          {job && (
            <section className="card">
              <h2>Текущая задача</h2>
              <p className="muted">
                {job.job_id} — <strong>{jobStatusRu(job.status)}</strong>
              </p>
              {job.progress_total > 0 && (
                <>
                  <div className="progress">
                    <div style={{ width: `${progressPct}%` }} />
                  </div>
                  <p className="muted">
                    {job.progress_done} / {job.progress_total}
                  </p>
                </>
              )}
              {job.error && <p style={{ color: "var(--danger)" }}>{job.error}</p>}
              <div className="log-box">{job.logs.join("\n") || "…"}</div>
              {job.status === "done" && firstRecentSite && (
                <div className="row-actions" style={{ marginTop: "0.75rem" }}>
                  <a href={previewUrl(firstRecentSite)} target="_blank" rel="noreferrer">
                    Открыть последний сайт
                  </a>
                  <a href={zipUrl(firstRecentSite)}>Скачать zip</a>
                  <button type="button" className="btn-secondary" onClick={() => setTab("outputs")}>
                    Перейти в результаты
                  </button>
                </div>
              )}
            </section>
          )}

          <div className="actions">
            <button type="button" className="btn" disabled={submitting} onClick={() => void onSubmit()}>
              {submitting ? "Запуск…" : "Сгенерировать"}
            </button>
          </div>
        </>
      )}

      {tab === "outputs" && (
        <section className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
            <h2 style={{ margin: 0 }}>Сгенерированные сайты</h2>
            <button type="button" className="btn-secondary" onClick={() => void loadSites()}>
              Обновить
            </button>
          </div>
          {sites.length === 0 ? (
            <p className="muted">В output пока нет папок с сайтами.</p>
          ) : (
            <div style={{ overflowX: "auto", marginTop: "1rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>Папка</th>
                    <th>Бренд</th>
                    <th>Шаблон</th>
                    <th>Архив</th>
                    <th>Путь</th>
                  </tr>
                </thead>
                <tbody>
                  {sites.map((s) => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td>{s.brand_name || "—"}</td>
                      <td>{s.template_id || "—"}</td>
                      <td>
                        <span className="row-actions">
                          <a href={previewUrl(s.name)} target="_blank" rel="noreferrer">
                            Открыть
                          </a>
                          <a href={zipUrl(s.name)}>Скачать</a>
                          {s.has_zip && <span className="muted">(уже есть)</span>}
                          <button type="button" className="btn-secondary" onClick={() => void onDeleteSite(s.name)}>
                            Удалить
                          </button>
                        </span>
                      </td>
                      <td>
                        <span className="row-actions">
                          <button type="button" className="btn-secondary" onClick={() => void copyPath(s.path)}>
                            Копировать путь
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "history" && (
        <section className="card">
          <h2>Недавние запуски</h2>
          <p className="muted">Хранится в output/.ui_runs.json (до 30 записей).</p>
          {history.length === 0 ? (
            <p className="muted">Истории пока нет.</p>
          ) : (
            <div className="log-box" style={{ maxHeight: 360 }}>
              {JSON.stringify(history, null, 2)}
            </div>
          )}
        </section>
      )}

      {toast && (
        <div className={`toast${toastErr ? " err" : ""}`} role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
