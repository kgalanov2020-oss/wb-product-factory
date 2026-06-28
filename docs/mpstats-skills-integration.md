# MPStats skills integration

## Analytics

For products without our WB listing, the analysis flow is:

1. Search WB competitors by product name:
   `POST https://mpstats.io/api/analytics/v1/wb/items?keyword=...`
2. Take competitor WB item IDs from the search result.
3. Enrich each competitor through SKU analytics:
   `GET https://mpstats.io/api/analytics/v1/wb/items/{id}/full?d1=YYYY-MM-DD&d2=YYYY-MM-DD`
4. Use `period_stats.sales`, `period_stats.revenue`, and `price.final_price`/`price.wallet_price` for market metrics.

The keyword search endpoint alone is not enough: it returns product cards, seller, brand, image and URL, but not reliable sales and revenue metrics.

Use `MPSTATS_TOKEN` as the primary environment variable. `MPSTATS_API_TOKEN` remains supported as a legacy alias.

## Photo Editor

The MPStats Photo Editor skill can be used as an additional image provider alongside Aidentika:

- `photoshoot` for product lifestyle/studio image sets.
- `infographics` for marketplace card slides.
- `remove-background`, `replace-background`, `upscale`, `recolor`, `in-action`, `freeform` for one-step edits.

For existing WB cards, the input can be `wb:<WB article>`; the skill downloads WB product photos and passes the first image as the main image plus up to five references.

Recommended product-card pipeline:

1. Generate text content with GPT/Gemini.
2. Generate visual candidates through Aidentika and MPStats Photo Editor.
3. Score candidates with GPT/Gemini against WB card requirements.
4. Save the selected card package to `product_content_jobs` and expose it in the UI for approval/export.
