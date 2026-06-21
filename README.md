# WB Product Factory

Автоматизированная система поиска, анализа и запуска новых товаров Wildberries.

## Цель

Автоматически находить перспективные товары из прайса поставщика «Звезда», анализировать рынок через MPStats, рассчитывать рентабельность, создавать контент через Aidentika и запускать новые карточки товаров на Wildberries.

---

## Технологический стек

### Backend

* Python 3.12
* FastAPI

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
