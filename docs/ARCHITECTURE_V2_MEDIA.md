# Architecture V2: dynamic media (optional epic)

The generator today emits **static files** (HTML/PHP, assets, `sitemap.xml`). The product brief that asks for **PostgreSQL + `/api/articles`** is a **separate layer**: either a new service or a migration path.

## 1. Suggested relational schema

| Table | Purpose |
| --- | --- |
| `sites` | Site id, brand name, base URL, vertical, theme, build metadata |
| `authors` | Slug, display name, bio, photo URL |
| `categories` | Slug, label, description |
| `articles` | Slug, title, dek, body (HTML or blocks), published_at, category_id, author_id, kind, word_count, hero_image_url |
| `tags` | Normalized tag names |
| `article_tags` | Many-to-many |
| `comments` | Optional: article_id, author display, body, created_at (if you need moderation) |
| `media_assets` | Stored path or remote URL, alt text, license, width/height |

## 2. Import path from static bundle

1. **Export job** (batch): after `run_generation`, write `site.json` next to the site root (flattened `brand` + `content` + list of articles with anchors and file paths).
2. **ETL**: a small importer reads `site.json`, uploads binaries to object storage if needed, inserts rows.
3. **Idempotency**: key on `(site_id, slug)` and upsert.

This keeps the current generator as the authoring surface while the API serves the same content dynamically.

## 3. Greenfield API (alternative)

- **FastAPI** + **SQLAlchemy** (or asyncpg) with the schema above.
- **Public routes**: `GET /articles`, `GET /articles/{slug}`, filters for category, tag, author.
- **Front**: SSG/SSR that calls the API at build time, or a SPA — outside this repo or as `apps/web` in a monorepo.

## 4. Environment variables (stock images)

- `UNSPLASH_ACCESS_KEY` — required for Unsplash-backed `images.image_source: unsplash` in the static generator.
- Wikimedia Commons uses the public API without a key (respect rate limits and licensing in production).

## 5. What stays in V1

Geo profiles, article kinds, tags, related posts, SEO/JSON-LD, and image providers improve the **static** output only. They do not replace a database-backed CMS.
