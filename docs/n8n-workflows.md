# n8n workflows

Raw n8n exports are kept local in `n8n_exports/` and ignored by git because they can include
workflow metadata and credential references. To refresh the generated summary, export workflow
JSON files into `n8n_exports/`, then run:

```bash
python tools/summarize_n8n_workflows.py
```

## WB workflow map

### WF 1 WB Остатки — снимок

Gets WB stock data from `statistics-api.wildberries.ru/api/v1/supplier/stocks`, normalizes it
into sheet columns, and appends rows to `WB Остатки`.

Core fields:

- `Дата снимка`
- `Артикул WB`
- `Бренд`
- `Предмет`
- `Артикул продавца`
- `Остаток на складах`
- `В пути до клиента`
- `В пути возвраты`

### WF 2 WB Аналитика — продажи по остаткам

Reads `WB Остатки` and `Справочник Звезда`, calculates stock/sales analytics, clears and rewrites
the `Аналитика` sheet.

Important logic to move into backend later:

- weighted demand calculation with month/week weights;
- matching WB stock rows with the Zvezda catalog;
- calculating recommended stock/order fields.

### WF 3 Заказ поставщику

Reads `Аналитика`, builds supplier order rows, converts them to a file, and sends the order by email.

This should become the backend purchase proposal module after approval is added.

### WF 4 Контроль дефицита

Reads `Аналитика`, detects deficit rows, sends a Telegram alert, builds an order file, uploads it
to Google Drive, and appends the event to `Журнал_заказов`.

This is the existing approval/reporting base for reorder automation.

### WF 5 Telegram Callback

Handles Telegram callbacks for approval/rejection, updates `Журнал_заказов`, downloads order files
from Google Drive, and sends emails/messages after action.

This maps to the future natural-language approval flow where GPT can interpret commands like
`убери этот танк` or `добавь 100 штук клея`.

### WF 6 GPT Аналитик WB

Collects WB sales, stock, finance, and ads data, prepares business metrics, sends a prompt to OpenAI,
sends Telegram analytics, and writes top products to `ТОП_товары`.

This is the existing GPT analytics base.

### WF 7 Конкуренты

Reads `ТОП_товары`, prepares search queries, calls WB public search and card APIs, and gathers
competitor information.

This maps to the competitor collector for current and candidate products.

### WF8 Рейтинг карточек и новых товаров

Reads `Прайс Звезда`, `Справочник Звезда`, and `Аналитика`; prepares a rating and writes
`Рейтинг карточек`.

This is the closest existing workflow to the product factory candidate list:

- products already listed on WB;
- products not yet listed;
- launch/card creation priority.

### WF9 Приоритет создания карточек

Reads `Рейтинг карточек`, filters rows where WB card does not exist and price is usable, limits the
batch, and calls MPStats.

This should become the first backend pipeline for: `missing_on_wb -> MPStats analysis -> card task`.
