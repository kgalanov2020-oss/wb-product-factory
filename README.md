# WB Product Factory

Автоматизированная система поиска, анализа и запуска новых товаров Wildberries.

## Цель

Автоматически находить перспективные товары из прайса поставщика «Звезда», анализировать рынок через MPStats, рассчитывать рентабельность, создавать контент через Aidentika и запускать новые карточки товаров на Wildberries.

---

## Технологический стек

### Backend

* Python 3.12
* FastAPI

### Frontend

* React
* Vite

### Browser Automation

* Playwright

### Database

* Supabase (PostgreSQL)

### AI

* OpenAI API

### Storage

* Google Drive

### Reporting

* Google Sheets API

### Automation

* n8n

### Hosting

* Render

---

## Основные модули

### MPStats Collector

Функции:

* авторизация в MPStats через Playwright
* сохранение cookies
* поиск товаров по названию
* поиск ниш
* сбор конкурентов
* сбор продаж
* сбор цен
* сбор выручки

Сохранение данных в Supabase.

---

### Scoring Engine

Рассчитывает:

* маржу
* конкуренцию
* емкость рынка
* потенциальную прибыль
* риск

Результат:

launch_score (0-100)

---

### Candidate Selector

Формирует:

TOP-100 товаров для запуска.

---

### GPT Analyzer

Для каждого товара:

* преимущества
* недостатки
* рекомендации
* риски

---

### Aidentika Generator

Автоматическая генерация:

* главное фото
* инфографика
* видео
* rich контент

---

### SEO Generator

Создает:

* название
* описание
* ключевые слова
* характеристики

---

### Approval System

Telegram бот:

Кнопки:

* Создать карточку
* Отложить
* Отклонить
* Показать конкурентов
* Показать расчёт

---

### Wildberries Publisher

Создание карточек через API WB.

---

## Структура проекта

/backend

/mpstats

/playwright

/aidentika

/openai

/supabase

/google

/n8n

/docs

/tests

---

## MVP v1

Первая задача:

1. Авторизация в MPStats
2. Поиск товара по названию
3. Сбор конкурентов
4. Сбор продаж
5. Запись в Supabase

После успешного MVP перейти к генерации карточек.

---

## Реализованные API endpoints

### System

* `GET /health` - проверка доступности API.
* `GET /api/v1/integrations/health` - проверка, настроены ли Supabase, MPStats и Aidentika.

### MPStats

* `POST /api/v1/mpstats/collect`

Пример:

```json
{
  "query": "клей звезда"
}
```

Endpoint запускает браузерный сбор MPStats, сохраняет результат в Supabase при наличии настроек и возвращает снимок данных.

### Aidentika

* `POST /api/v1/aidentika/analyze` - анализ изображения.
* `POST /api/v1/aidentika/generate/photo` - запуск генерации товарного фото.
* `POST /api/v1/aidentika/generate/card` - запуск генерации карточки/инфографики.
* `GET /api/v1/aidentika/status/{action_id}` - проверка статуса асинхронной генерации.

Пример генерации карточки:

```json
{
  "images": [
    {
      "url": "https://example.com/product.jpg"
    }
  ],
  "product_name": "Клей Звезда",
  "user_text": "Инфографика для карточки Wildberries: назначение, преимущества, объем, способ применения",
  "concept_id": "infographic",
  "aspect_ratio": "3:4",
  "style": "classic"
}
```

### Product Content

* `POST /api/v1/product-content/generate` - WB-оркестратор генерации контента по товару.
* `GET /api/v1/product-content/jobs/{job_id}` - получить сохраненную задачу и ее Aidentika actions.
* `POST /api/v1/product-content/jobs/{job_id}/sync` - обновить статусы actions из Aidentika и пересчитать статус job.

Endpoint принимает товар, фото и список нужных материалов, затем запускает несколько задач Aidentika и возвращает `job_id` и `action_id` по каждому материалу.

Пример:

```json
{
  "product_name": "Клей Звезда",
  "brand": "Звезда",
  "images": [
    {
      "url": "https://example.com/product.jpg"
    }
  ],
  "assets": ["main_photo", "infographic", "advantages", "usage"],
  "facts": [
    "для сборных моделей",
    "подходит для пластика",
    "точное нанесение"
  ],
  "target_audience": "покупатели сборных моделей и товаров для хобби"
}
```

Жизненный цикл:

1. `POST /api/v1/product-content/generate`
2. сохранить `job_id` из ответа
3. периодически вызывать `POST /api/v1/product-content/jobs/{job_id}/sync`
4. читать результат через `GET /api/v1/product-content/jobs/{job_id}`

### Supplier Products

* `POST /api/v1/supplier-products/import-url` - импорт прайса по публичной CSV/XLSX-ссылке.
* `POST /api/v1/supplier-products/import-file` - импорт прайса из CSV/XLSX-файла.
* `GET /api/v1/supplier-products` - список товаров поставщика.
* `GET /api/v1/supplier-products/{product_id}` - карточка товара поставщика.

Для Google Sheets ссылка должна быть доступна без входа в Google. Если обычная ссылка открывает страницу таблицы, для CSV-импорта нужен формат:

```text
https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv
```

---

## Переменные окружения

Минимум для MPStats:

```env
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_MPSTATS_TABLE=mpstats_collections
MPSTATS_EMAIL=
MPSTATS_PASSWORD=
```

Минимум для Aidentika:

```env
AIDENTIKA_BASE_URL=https://api.aidentika.com/api/v1/public
AIDENTIKA_API_KEY=
```

---

## Ближайший план

1. Стабилизировать извлечение полезных данных из MPStats: `competitors`, `sales`, `prices`, `revenue`.
2. Добавить нормализацию MPStats-ответов в отдельные таблицы.
3. Добавить `product_candidates` и расчет `launch_score`.
4. Связать выбранного кандидата с Aidentika: товарные фото и инфографика.
5. Сохранять готовые изображения Aidentika в Supabase Storage или Google Drive.
6. Добавить связь `product_candidates -> product_content_jobs`.

---

## Supabase schema

SQL-схема лежит в `supabase/schema.sql`.

Она создает:

* `mpstats_collections`
* `product_content_jobs`
* `product_content_actions`
* `supplier_products`
* `product_analyses`

---

## Frontend

Локальный запуск интерфейса:

```bash
cd frontend
npm install
npm run dev
```

По умолчанию интерфейс работает с API:

```text
https://wb-product-factory-api.onrender.com
```

Для другого API можно задать:

```env
VITE_API_URL=http://localhost:8000
```
