/** Синхронизировать с generators/newsroom_articles.py: NEWS_CATEGORIES и _ARTICLE_BLUEPRINTS */

export const NEWS_CATEGORIES = [
  "Technology",
  "Business",
  "World",
  "Science",
  "Politics",
  "Culture",
  "Health",
] as const;

export type NewsCategory = (typeof NEWS_CATEGORIES)[number];

/** Подписи рубрик в форме (ключ = как в API/генераторе) */
export const NEWS_CATEGORY_LABELS_RU: Record<NewsCategory, string> = {
  Technology: "Технологии",
  Business: "Бизнес",
  World: "Мир",
  Science: "Наука",
  Politics: "Политика",
  Culture: "Культура",
  Health: "Здоровье",
};

export const ARTICLE_KINDS = ["news", "analysis", "column"] as const;
export type ArticleKind = (typeof ARTICLE_KINDS)[number];

export const ARTICLE_KIND_LABELS_RU: Record<ArticleKind, string> = {
  news: "Новость (коротко)",
  analysis: "Разбор / аналитика",
  column: "Колонка / мнение",
};

/** Индекс, рубрика, начало заголовка — чтобы в UI было понятно, о какой статье речь */
export const NEWS_BLUEPRINT_SLOTS: { category: NewsCategory; titleHint: string }[] = [
  { category: "Technology", titleHint: "Inside the chip supply chain…" },
  { category: "Business", titleHint: "Why city budgets are bracing…" },
  { category: "World", titleHint: "Field note: how aid routes shift…" },
  { category: "Science", titleHint: "Heat records aren't hype…" },
  { category: "Politics", titleHint: "Local races are drawing national money…" },
  { category: "Culture", titleHint: "Streaming rights reshaped the festival…" },
  { category: "Technology", titleHint: "The patchwork of AI disclosure laws…" },
  { category: "Business", titleHint: "Small exporters are hedging currency…" },
  { category: "World", titleHint: "Correspondents on the ground…" },
  { category: "Science", titleHint: "A public lab opened its notebooks…" },
  { category: "Politics", titleHint: "Redistricting fights moved to spreadsheets…" },
  { category: "Culture", titleHint: "Museums are lending more, owning less…" },
  { category: "Technology", titleHint: "Cyber incident disclosures…" },
  { category: "Business", titleHint: "Interest rates meets rent…" },
  { category: "World", titleHint: "Diplomatic language vs. satellite evidence…" },
  { category: "Science", titleHint: "Clinical trial transparency…" },
  { category: "Politics", titleHint: "Coalitions form earlier now…" },
  { category: "Culture", titleHint: "Indie venues and insurance…" },
  { category: "Technology", titleHint: "Cloud outages rippled through hospitals…" },
  { category: "Business", titleHint: "Venture debt isn't glamorous…" },
  { category: "Health", titleHint: "ER wait times and triage protocols…" },
  { category: "Health", titleHint: "Drug shortage ripples reach…" },
  { category: "Health", titleHint: "Public health dashboards: lag, bias…" },
];
