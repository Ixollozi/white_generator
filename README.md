# White Generator

Генератор “вайтов” из шаблонов (pages + components) с простым UI на React. Делает:
- сборку HTML/“PHP-обёрток” по слотам шаблона
- бренд и тексты (seed/детерминизм)
- SEO-файлы (sitemap.xml / robots.txt)
- “шум” (доп. пустые CSS/JS файлы + служебные страницы)
- загрузку своих изображений (asset packs) и показ их в сайте (в upload-режиме)

---

## Как запустить

### Dev (FastAPI + Vite)
1. `cd` в корень проекта: `White_generator`
2. Установить зависимости (если нужно):
   - `pip install -r requirements.txt`
   - `cd frontend && npm install && cd ..`
3. Запуск:
   - `python start_dev.py --open-browser`
   - или без открытия браузера: `python start_dev.py`

Скрипт держит **один экземпляр** dev-окружения и стартует API + frontend.

### Запуск генерации (CLI)
`python main.py generate [config_file] [flags]`

Примеры:
- На базе конфига:
  - `python main.py generate configs/default.yaml --count 3 --zip`
- Только флагами:
  - `python main.py generate --count 2 --templates corporate_v1 --seed 7`

---

## Где лежат исходники и что генерируется

### Шаблоны
`templates/<template_id>/template.yaml`
- `layout`: файл layout (обычно `layout.html`)
- `page_extension`: расширение сгенерированных файлов (например `php`)
- `pages`: список страниц и их слотов

`templates/<template_id>/layout.html`
- общий “каркас” страницы
- вставляет `body_html`
- указывает блоки вроде `{{ integrations.tracking_html | safe }}`

### Компоненты (слоты)
`components/<component_type>/meta.yaml`
- `required_vars`: какие переменные обязаны быть в контексте
- `variants`: список html-вариантов компонента

Компонент выбирается случайно из вариантов по `seed`.

### Тексты и данные
Используются:
- `data/industries.yaml`
- `data/services.yaml`

Генерация контента и “бренда” находится в:
- `generators/brand_generator.py`
- `generators/content_generator.py`

---

## Темы оформления

Тема — это набор ассетов в:
`assets/themes/<theme>/css|js|img`

Выбранная тема копируется в каждый сгенерированный сайт:
`output/<site>/css`, `output/<site>/js`, `output/<site>/img`

UI берёт список тем через `GET /api/themes`.

---

## Изображения (asset packs)

### Загрузка
В UI режим `Изображения -> upload (свои)`:
- выбираете файлы
- нажимаете “Загрузить”

Сервер сохраняет их в:
`assets/asset_packs/<asset_pack_id>/originals/`

### Просмотр / удаление
В UI есть список наборов (packs), оттуда можно:
- просмотреть миниатюры
- удалить набор целиком

### Подстановка в генерацию (наглядность)
Сейчас изображения **используются в генерации в upload-режиме**:
- файлы копируются в `output/<site>/img/upload/`
- в `templates/*/layout.html` добавлен блок-галерея, который показывает загруженные картинки (если `images.items` не пустой)

`web (скачать)` режим пока не реализован (в коде генератора поддержан upload).

---

## SEO и “шум”

### SEO
Опции:
- `seo.generate_sitemap` → пишет `sitemap.xml`
- `seo.generate_robots` → пишет `robots.txt`

Ключевая логика SEO в `core/seo_engine.py`.

### “Шум”
Опции (реально используются сейчас):
- `noise.extra_css_max` / `noise.extra_js_max` → создают пустые/заглушечные файлы в `output/<site>/css` и `output/<site>/js`
- `noise.junk_pages` → добавляют служебные страницы (privacy/terms/cookie) как обычные страницы сайта

Параметры вроде `attach_assets`, `randomize_classes`, `randomize_ids` в UI пока не подключены в реальную логику генерации (запрашиваются/хранятся, но не меняют HTML).

---

## Параметры генерации (конфиг)

Ключи по умолчанию описаны в `core/config_loader.py` и `configs/default.yaml`.

Самое важное:
- `count` — сколько сайтов сгенерировать
- `templates` — список шаблонов
- `base_url` — база для sitemap
- `theme` — тема ассетов
- `seed` — глобальный seed (на каждый сайт берётся производная)
- `strict_components` — если включено и в компоненте не хватает нужных переменных, генерация падает с ошибкой
- `brand`:
  - `domain_mode`: `none | brand_tld | random_tld | custom`
  - `custom_domain`: используется при `domain_mode=custom`
- `images`:
  - `mode`: `none | web | upload`
  - `asset_pack_id`: какой pack использовать в `upload`
- `integrations`:
  - `offer_link`: placeholder (в текущих шаблонах используется как “комментарий-заглушка” через `tracking_html`)

---

## API (если нужно интегрироваться)

Основные эндпоинты (FastAPI, `server/app.py`):
- `GET /api/health`
- `GET /api/templates`
- `GET /api/themes`
- `POST /api/generate` — старт генерации (возвращает `job_id`)
- `GET /api/jobs/{job_id}` — статус/логи/ошибка
- `GET /api/output/sites` — список сгенерированных сайтов
- `DELETE /api/output/sites/{site_name}` — удалить сайт
- `GET /api/output/sites/{site_name}/preview/` — превью
- `GET /api/output/sites/{site_name}/zip` — скачать архив

Изображения:
- `POST /api/images/upload` — загрузка файлов, возвращает `asset_pack_id`
- `GET /api/images/packs` — список pack’ов
- `GET /api/images/packs/{asset_pack_id}` — список файлов в pack’e
- `GET /api/images/packs/{asset_pack_id}/files/{file_name}` — отдать файл
- `DELETE /api/images/packs/{asset_pack_id}` — удалить pack

---

## Тесты

`pytest`:
- проверяет базовую генерацию
- проверяет brand/domain mode
- проверяет, что upload-mode копирует изображения и что они появляются в HTML-выводе

---

## Примечание по текущему состоянию

Некоторые настройки присутствуют в UI, но не полностью влияют на генерацию (например, части “noise/randomize_*” и “keywords”). Если хочешь — могу доподключить недостающую логику и описать её в README.

