import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  Boxes,
  CheckCircle2,
  FileSpreadsheet,
  ImagePlus,
  RefreshCcw,
  Search,
  Settings,
  Upload,
} from "lucide-react";
import "./styles.css";

const RENDER_API_URL = "https://wb-product-factory-api.onrender.com";
const LOCAL_API_URL = "http://127.0.0.1:8000";
const API_URL_STORAGE_KEY = "wb-product-factory-api-url";
const ZVEZDA_PRICE_URL =
  "https://docs.google.com/spreadsheets/d/1foAGehT70Vlquawlwrz4K2AITELWuIV5tumFBOT6q5I/edit?usp=sharing";
const DEFAULT_API_URL = import.meta.env.VITE_API_URL ?? RENDER_API_URL;

type Integrations = {
  supabase: boolean;
  mpstats_login: boolean;
  mpstats_api: boolean;
  aidentika: boolean;
  openai: boolean;
  gemini: boolean;
  wb_content: boolean;
};

type SupplierProduct = {
  id: string;
  supplier: string;
  sku?: string | null;
  name: string;
  category?: string | null;
  wholesale_price?: string | null;
  retail_price?: string | null;
  stock?: number | null;
  pack_units?: number | null;
  weight_grams?: string | null;
  dimensions?: string | null;
  description?: string | null;
  order_quantity?: number | null;
  photo_urls: string[];
  source_url?: string | null;
  status: string;
  launch_score?: number | null;
};

type ProductListResponse = {
  products: SupplierProduct[];
  total: number;
};

type ProductStatsResponse = {
  total: number;
  missing_on_wb: number;
  listed: number;
  analyzed: number;
  content_ready: number;
};

type ContentJob = {
  job_id: string;
  status: string;
  product_name: string;
  request_payload?: {
    card_draft?: WBCardDraft;
  };
  actions: Array<{
    asset_type: string;
    action_id: number;
    status: string;
    result_url?: string | null;
    error_message?: string | null;
  }>;
};

type WBCardDraft = {
  vendor_code?: string | null;
  barcode?: string | null;
  brand?: string | null;
  title?: string | null;
  subject?: string | null;
  description?: string | null;
  characteristics?: Record<string, string | number | null>;
  dimensions?: Record<string, string | number | null>;
  recommended_price?: string | number | null;
  source_images?: string[];
  generated_images?: string[];
};

type WBUploadResult = {
  status: string;
  message: string;
  payload?: WBCardDraft;
};

type RecommendedContentResult = {
  requested: number;
  started: number;
  skipped: Array<{
    product_id: string;
    product_name: string;
    reason: string;
  }>;
  jobs: ContentJob[];
};

type AnalysisState = {
  status: "running" | "completed" | "failed";
  message: string;
  details?: ProductAnalysis;
};

type ProductAnalysis = {
  status: string;
  market_price_min?: string | null;
  market_price_avg?: string | null;
  market_price_max?: string | null;
  competitor_count?: number | null;
  estimated_sales?: number | null;
  estimated_revenue?: string | null;
  margin_percent?: number | null;
  launch_score?: number | null;
  notes?: string | null;
  raw?: {
    analysis_period?: {
      label?: string;
      date_from?: string;
      date_to?: string;
      price_basis?: string;
      sales_basis?: string;
      revenue_basis?: string;
      margin_basis?: string;
      score_basis?: string;
    };
    period_rollups?: Record<string, PeriodStats>;
    mpstats_snapshot?: {
      competitors?: Array<{
        name?: string | null;
        brand?: string | { name?: string | null } | null;
        supplier?: string | { name?: string | null } | null;
        price?: string | number | null;
        sales?: number | null;
        revenue?: string | number | null;
        nm_id?: string | number | null;
        rating?: string | number | null;
        feedbacks?: string | number | null;
        stock?: string | number | null;
        url?: string | null;
        periods?: Record<string, PeriodStats>;
      }>;
    };
  };
};

type PeriodStats = {
  label?: string;
  date_from?: string | null;
  date_to?: string | null;
  sales?: string | number | null;
  revenue?: string | number | null;
};

type Competitor = NonNullable<
  NonNullable<NonNullable<ProductAnalysis["raw"]>["mpstats_snapshot"]>["competitors"]
>[number];

type Page = "price" | "products" | "analysis" | "content" | "settings";

function App() {
  const [page, setPage] = useState<Page>(() => pageFromHash(window.location.hash));
  const [apiUrl, setApiUrl] = useState(() => {
    const savedApiUrl = localStorage.getItem(API_URL_STORAGE_KEY);
    return savedApiUrl === LOCAL_API_URL ? DEFAULT_API_URL : savedApiUrl ?? DEFAULT_API_URL;
  });
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [products, setProducts] = useState<SupplierProduct[]>([]);
  const [recommendations, setRecommendations] = useState<SupplierProduct[]>([]);
  const [productStats, setProductStats] = useState<ProductStatsResponse | null>(null);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<SupplierProduct | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sheetUrl, setSheetUrl] = useState(ZVEZDA_PRICE_URL);
  const [message, setMessage] = useState("");
  const [jobs, setJobs] = useState<ContentJob[]>([]);
  const [analysisState, setAnalysisState] = useState<Record<string, AnalysisState>>({});
  const [loading, setLoading] = useState(false);

  const stats = useMemo(() => {
    const ready = jobs.filter((job) => job.status === "completed").length;
    const running = jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
    return {
      products: productStats?.total ?? total,
      contentReady: ready,
      contentRunning: running,
      missing: productStats?.missing_on_wb ?? products.filter((product) => product.status === "missing_on_wb").length,
    };
  }, [jobs, productStats, products, total]);

  useEffect(() => {
    localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);
  }, [apiUrl]);

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function navigate(nextPage: Page) {
    setPage(nextPage);
    window.location.hash = nextPage;
  }

  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${apiUrl}${path}`, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail ?? `Ошибка API: ${response.status}`);
    }
    return payload as T;
  }

  async function refresh() {
    setLoading(true);
    setMessage("");
    try {
      const [health, stats, productList, recommendationList, contentJobs] = await Promise.all([
        request<Integrations>("/api/v1/integrations/health"),
        request<ProductStatsResponse>("/api/v1/supplier-products/stats"),
        request<ProductListResponse>("/api/v1/supplier-products?limit=100"),
        request<ProductListResponse>("/api/v1/supplier-products/recommendations?limit=10"),
        request<ContentJob[]>("/api/v1/product-content/jobs?limit=20"),
      ]);
      setIntegrations(health);
      setProductStats(stats);
      setProducts(productList.products);
      setRecommendations(recommendationList.products);
      setTotal(productList.total);
      setJobs(contentJobs);
      setSelected((current) => {
        if (!current) {
          return productList.products[0] ?? null;
        }
        return productList.products.find((product) => product.id === current.id) ?? current;
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка обновления");
    } finally {
      setLoading(false);
    }
  }

  async function importFile() {
    if (!file) {
      setMessage("Выберите CSV или XLSX файл прайса.");
      return;
    }
    setLoading(true);
    setMessage("");
    const form = new FormData();
    form.append("supplier", "zvezda");
    form.append("file", file);
    try {
      const result = await request<{ imported: number }>("/api/v1/supplier-products/import-file", {
        method: "POST",
        body: form,
      });
      setMessage(`Импортировано товаров: ${result.imported}`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка импорта");
    } finally {
      setLoading(false);
    }
  }

  async function importUrl() {
    if (!sheetUrl.trim()) {
      setMessage("Вставьте публичную ссылку Google Sheets.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const result = await request<{ imported: number }>("/api/v1/supplier-products/import-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: sheetUrl.trim(), supplier: "zvezda" }),
      });
      setMessage(`Импортировано товаров: ${result.imported}`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка импорта");
    } finally {
      setLoading(false);
    }
  }

  async function generateContent(product: SupplierProduct) {
    setLoading(true);
    setMessage("");
    try {
      const job = await request<ContentJob>(`/api/v1/product-content/supplier-products/${product.id}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assets: ["main_photo", "infographic", "advantages", "usage"] }),
      });
      setJobs((current) => [job, ...current]);
      setMessage(`Запущена генерация: ${job.job_id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка генерации");
    } finally {
      setLoading(false);
    }
  }

  async function generateRecommendedContent() {
    setLoading(true);
    setMessage("");
    try {
      const result = await request<RecommendedContentResult>("/api/v1/product-content/recommended/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          limit: 3,
          min_score: 50,
          assets: ["main_photo", "infographic", "advantages", "usage"],
        }),
      });
      setJobs((current) => [...result.jobs, ...current]);
      const skipped = result.skipped.length ? `, пропущено: ${result.skipped.length}` : "";
      setMessage(`Запущено генераций: ${result.started}${skipped}`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка генерации рекомендаций");
    } finally {
      setLoading(false);
    }
  }

  async function analyzeProduct(product: SupplierProduct) {
    setLoading(true);
    const runningMessage = `Запущен анализ: ${product.name}`;
    setMessage(runningMessage);
    setAnalysisState((current) => ({
      ...current,
      [product.id]: { status: "running", message: "Анализ идет. Обычно это занимает 30-90 секунд." },
    }));
    try {
      const analysis = await request<ProductAnalysis>(
        `/api/v1/supplier-products/${product.id}/analyze`,
        { method: "POST" },
      );
      if (analysis.status === "failed") {
        const failedMessage = `Анализ не выполнен: ${analysis.notes ?? "источник данных временно недоступен"}`;
        setMessage(failedMessage);
        setAnalysisState((current) => ({
          ...current,
          [product.id]: { status: "failed", message: failedMessage, details: analysis },
        }));
      } else {
        const doneMessage = analysisSummary(analysis);
        setMessage(doneMessage);
        setAnalysisState((current) => ({
          ...current,
          [product.id]: { status: "completed", message: doneMessage, details: analysis },
        }));
      }
      await refresh();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Ошибка анализа";
      setMessage(errorMessage);
      setAnalysisState((current) => ({
        ...current,
        [product.id]: { status: "failed", message: errorMessage },
      }));
    } finally {
      setLoading(false);
    }
  }

  async function loadProductAnalysis(product: SupplierProduct) {
    if (!["analyzed", "analysis_pending"].includes(product.status)) {
      return;
    }
    try {
      const analysis = await request<ProductAnalysis>(`/api/v1/supplier-products/${product.id}/analysis`);
      const analysisStatus =
        analysis.status === "completed" ? "completed" : analysis.status === "failed" ? "failed" : "running";
      const analysisMessage =
        analysis.status === "completed"
          ? analysisSummary(analysis)
          : `Анализ не выполнен: ${analysis.notes ?? "нет данных"}`;
      setAnalysisState((current) => ({
        ...current,
        [product.id]: { status: analysisStatus, message: analysisMessage, details: analysis },
      }));
    } catch {
      // Analysis may not exist yet for legacy rows.
    }
  }

  async function syncJob(jobId: string) {
    setLoading(true);
    try {
      const job = await request<ContentJob>(`/api/v1/product-content/jobs/${jobId}/sync`, {
        method: "POST",
      });
      setJobs((current) => current.map((item) => (item.job_id === jobId ? job : item)));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка обновления задачи");
    } finally {
      setLoading(false);
    }
  }

  async function uploadJobToWb(jobId: string) {
    setLoading(true);
    try {
      const result = await request<WBUploadResult>(`/api/v1/product-content/jobs/${jobId}/upload-wb`, {
        method: "POST",
      });
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка выгрузки в WB");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (selected) {
      loadProductAnalysis(selected);
    }
  }, [selected?.id, selected?.status]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Boxes size={24} />
          <span>WB Factory</span>
        </div>
        <nav>
          <button className={page === "price" ? "active" : ""} onClick={() => navigate("price")}><FileSpreadsheet size={18} /> Прайс</button>
          <button className={page === "products" ? "active" : ""} onClick={() => navigate("products")}><Search size={18} /> Товары</button>
          <button className={page === "analysis" ? "active" : ""} onClick={() => navigate("analysis")}><BarChart3 size={18} /> Анализ</button>
          <button className={page === "content" ? "active" : ""} onClick={() => navigate("content")}><ImagePlus size={18} /> Контент</button>
          <button className={page === "settings" ? "active" : ""} onClick={() => navigate("settings")}><Settings size={18} /> Интеграции</button>
        </nav>
      </aside>

      <main>
        <header>
          <div>
            <h1>WB Product Factory</h1>
            <p>Анализ прайса, поиск кандидатов и генерация карточек Wildberries.</p>
          </div>
          <button className="icon-button" onClick={refresh} disabled={loading} title="Обновить">
            <RefreshCcw size={18} />
          </button>
        </header>

        {message ? <div className="notice">{message}</div> : null}

        <section className="metrics">
          <Metric label="Товаров в прайсе" value={stats.products} />
          <Metric label="Нет в продаже" value={stats.missing} />
          <Metric label="Контент в работе" value={stats.contentRunning} />
          <Metric label="Контент готов" value={stats.contentReady} />
        </section>

        {page === "price" ? <section className="panel page-panel">
          <div className="panel-title">
            <h2>Импорт прайса Звезда</h2>
            <span>CSV/XLSX или публичная ссылка Google Sheets</span>
          </div>
          <div className="import-grid">
            <label className="file-box">
              <Upload size={22} />
              <span>{file ? file.name : "Выбрать файл прайса"}</span>
              <input
                type="file"
                accept=".csv,.xlsx,.txt"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button onClick={importFile} disabled={loading}>Импортировать файл</button>
            <input
              value={sheetUrl}
              onChange={(event) => setSheetUrl(event.target.value)}
              placeholder="https://docs.google.com/spreadsheets/..."
            />
            <button onClick={importUrl} disabled={loading}>Импортировать URL</button>
          </div>
        </section> : null}

        {page === "products" ? <section className="workspace page-panel">
          <div className="panel product-list">
            <div className="panel-title">
              <h2>Товары</h2>
              <span>{total} позиций</span>
            </div>
            <div className="table">
              {products.map((product) => (
                <button
                  className={`row ${selected?.id === product.id ? "active" : ""}`}
                  key={product.id}
                  onClick={() => setSelected(product)}
                >
                  <span>{product.name}</span>
                  <em>{product.wholesale_price ? `${product.wholesale_price} ₽` : "цена ?"}</em>
                </button>
              ))}
              {!products.length ? <div className="empty">Прайс еще не импортирован.</div> : null}
            </div>
          </div>

          <div className="panel details">
            <div className="panel-title">
              <h2>{selected ? selected.name : "Товар не выбран"}</h2>
              <span>{formatProductStatus(selected?.status)}</span>
            </div>
            {selected ? (
              <>
                <div className="product-card">
                  {selected.photo_urls[0] ? <img src={selected.photo_urls[0]} alt={selected.name} /> : <div className="no-photo">Нет фото</div>}
                  <dl>
                    <dt>Артикул</dt><dd>{selected.sku ?? "не указан"}</dd>
                    <dt>Категория</dt><dd>{selected.category ?? "не указана"}</dd>
                    <dt>Описание</dt><dd>{selected.description ?? "не указано"}</dd>
                    <dt>Закупка</dt><dd>{selected.wholesale_price ?? "не указана"}</dd>
                    <dt>В коробке</dt><dd>{selected.pack_units ?? "не указано"}</dd>
                    <dt>Вес, гр</dt><dd>{selected.weight_grams ?? "не указан"}</dd>
                    <dt>Размер, мм</dt><dd>{selected.dimensions ?? "не указан"}</dd>
                    <dt>Заказ</dt><dd>{selected.order_quantity ?? "не указан"}</dd>
                  </dl>
                </div>
                <div className="actions">
                  <button onClick={() => generateContent(selected)} disabled={loading}>
                    Сгенерировать карточку
                  </button>
                  <button onClick={() => navigate("analysis")}>
                    Открыть анализ
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </section> : null}

        {page === "analysis" ? <section className="analysis-page page-panel">
          <div className="panel recommendations">
            <div className="panel-title">
              <h2>Топ-10 рекомендаций</h2>
              <span>только товары из прайса Звезда</span>
            </div>
            <div className="recommendation-list">
              {recommendations.map((product, index) => (
                <button
                  className="recommendation-row"
                  key={product.id}
                  onClick={() => setSelected(product)}
                >
                  <strong>{index + 1}</strong>
                  <span>{product.name}</span>
                  <em>оценка {product.launch_score?.toFixed(2)}</em>
                  <small>{recommendationReason(product)}</small>
                </button>
              ))}
              {!recommendations.length ? (
                <div className="empty">Топ появится после MPStats-анализа товаров.</div>
              ) : null}
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">
              <h2>{selected ? selected.name : "Товар не выбран"}</h2>
              <span>{selected ? formatProductStatus(selected.status) : "выберите товар"}</span>
            </div>
            {selected ? (
              <>
                <div className="product-card compact">
                  {selected.photo_urls[0] ? <img src={selected.photo_urls[0]} alt={selected.name} /> : <div className="no-photo">Нет фото</div>}
                  <dl>
                    <dt>Артикул</dt><dd>{selected.sku ?? "не указан"}</dd>
                    <dt>Закупка</dt><dd>{selected.wholesale_price ? `${selected.wholesale_price} ₽` : "не указана"}</dd>
                    <dt>Размер</dt><dd>{selected.dimensions ?? selected.description ?? "не указан"}</dd>
                    <dt>В коробке</dt><dd>{selected.pack_units ?? "не указано"}</dd>
                  </dl>
                </div>
                <div className="actions">
                  <button onClick={() => analyzeProduct(selected)} disabled={loading}>
                    {analysisState[selected.id]?.status === "running" ? "Анализ идет..." : "Пересчитать анализ"}
                  </button>
                  <button onClick={() => generateContent(selected)} disabled={loading}>
                    Сгенерировать карточку
                  </button>
                </div>
                {(() => {
                  const currentAnalysis = analysisState[selected.id];
                  return currentAnalysis ? (
                    <div className={`analysis-status ${currentAnalysis.status}`}>
                      <strong>{currentAnalysis.message}</strong>
                      {currentAnalysis.details ? <AnalysisDetails analysis={currentAnalysis.details} /> : null}
                    </div>
                  ) : (
                    <div className="empty">Для товара еще нет анализа. Нажмите “Пересчитать анализ”.</div>
                  );
                })()}
              </>
            ) : null}
          </div>
        </section> : null}

        {page === "content" ? <section className="panel page-panel">
          <div className="panel-title">
            <h2>Генерация контента и история</h2>
            <button onClick={generateRecommendedContent} disabled={loading}>
              Сгенерировать топ-рекомендации
            </button>
          </div>
          <div className="jobs">
            {jobs.map((job) => (
              <article className="job" key={job.job_id}>
                <div>
                  <strong>{job.product_name}</strong>
                  <span>{formatJobStatus(job.status)}</span>
                </div>
                <button onClick={() => syncJob(job.job_id)} disabled={loading}>Обновить</button>
                <button onClick={() => uploadJobToWb(job.job_id)} disabled={loading}>Выгрузить в WB</button>
                <WBCardDraftView draft={job.request_payload?.card_draft} />
                <div className="job-actions">
                  {job.actions.map((action) => (
                    <div key={action.action_id}>
                      <span>{action.asset_type}</span>
                      <em>{formatJobStatus(action.status)}</em>
                      {action.result_url ? <a href={action.result_url} target="_blank">Открыть</a> : null}
                    </div>
                  ))}
                </div>
              </article>
            ))}
            {!jobs.length ? <div className="empty">Задач генерации пока нет.</div> : null}
          </div>
        </section> : null}

        {page === "settings" ? <section className="panel page-panel">
          <div className="panel-title">
            <h2>Интеграции</h2>
            <span>{apiUrl.includes("127.0.0.1") || apiUrl.includes("localhost") ? "Локальный API" : "Render API"}</span>
          </div>
          <div className="api-switcher">
            <input value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} />
            <button type="button" onClick={() => setApiUrl(LOCAL_API_URL)}>Локально</button>
            <button type="button" onClick={() => setApiUrl(RENDER_API_URL)}>Render</button>
          </div>
          {!integrations?.mpstats_api ? (
            <div className="hint">
              MPStats API нужен для нового анализа продаж. Генерация карточек работает через Aidentika.
              Для полного анализа добавь MPSTATS_TOKEN в Render.
            </div>
          ) : null}
          <div className="status-grid">
            <Status label="Supabase" ok={integrations?.supabase} />
            <Status label="MPStats" ok={integrations?.mpstats_login} />
            <Status label="MPStats API" ok={integrations?.mpstats_api} />
            <Status label="Aidentika" ok={integrations?.aidentika} />
            <Status label="GPT" ok={integrations?.openai} />
            <Status label="Gemini" ok={integrations?.gemini} />
          </div>
        </section> : null}
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Status({ label, ok }: { label: string; ok?: boolean }) {
  return (
    <div className={`status ${ok ? "ok" : "bad"}`}>
      <CheckCircle2 size={18} />
      <span>{label}</span>
      <strong>{ok ? "подключено" : "нет"}</strong>
    </div>
  );
}

function AnalysisDetails({ analysis }: { analysis: ProductAnalysis }) {
  const period = analysis.raw?.analysis_period;
  return (
    <>
      <div className="analysis-period">
        <strong>Период: {period?.label ?? "последние 30 дней"}</strong>
        <span>{period?.date_from && period?.date_to ? `${period.date_from} - ${period.date_to}` : "MPStats-снимок за доступный период"}</span>
      </div>
      <PeriodRollups analysis={analysis} />
      <dl className="analysis-grid">
        <dt>Конкуренты</dt><dd>{analysis.competitor_count ?? "нет данных"}</dd>
        <dt>Цена рынка</dt><dd>{formatPriceRange(analysis)} <small>мин / средняя / макс</small></dd>
        <dt>Продажи за 30 дней</dt><dd>{formatNumber(analysis.estimated_sales)} <small>{period?.sales_basis ?? "сумма по конкурентам за 30 дней"}</small></dd>
        <dt>Выручка за 30 дней</dt><dd>{formatMoney(analysis.estimated_revenue)} <small>{period?.revenue_basis ?? "сумма по конкурентам за 30 дней"}</small></dd>
        <dt>Маржа</dt><dd>{formatPercent(analysis.margin_percent)} <small>{period?.margin_basis ?? "по средней цене рынка, без расходов WB"}</small></dd>
        <dt>Оценка запуска</dt><dd>{analysis.launch_score ?? "нет данных"} из 100 <small>чем выше, тем интереснее товар: учитываем маржу, спрос и количество конкурентов</small></dd>
        <dt>Вывод</dt><dd>{analysis.notes ?? "нет"}</dd>
      </dl>
      <TopCompetitors analysis={analysis} />
    </>
  );
}

function PeriodRollups({ analysis }: { analysis: ProductAnalysis }) {
  const rollups = analysis.raw?.period_rollups ?? {};
  const periods = [
    ["week", "7 дней"],
    ["month", "30 дней"],
    ["quarter", "90 дней"],
    ["year_to_date", "с начала года"],
  ] as const;
  if (!Object.keys(rollups).length) {
    return null;
  }
  return (
    <div className="period-table">
      <strong>Продажи по периодам</strong>
      <small>Сумма по релевантным конкурентам MPStats: штуки и деньги отдельно за каждый период.</small>
      <div className="period-row head">
        <span>Период</span>
        <span>Штуки</span>
        <span>Деньги</span>
      </div>
      {periods.map(([key, fallbackLabel]) => {
        const item = rollups[key];
        return (
          <div className="period-row" key={key}>
            <span>{item?.label ?? fallbackLabel}</span>
            <span>{formatNumber(item?.sales)}</span>
            <span>{formatMoney(item?.revenue)}</span>
          </div>
        );
      })}
    </div>
  );
}

function TopCompetitors({ analysis }: { analysis: ProductAnalysis }) {
  const competitors = (analysis.raw?.mpstats_snapshot?.competitors ?? [])
    .filter(hasAnyPeriodData)
    .sort((left, right) => competitorRevenue(right) - competitorRevenue(left))
    .slice(0, 10);
  if (!competitors.length) {
    return <div className="empty">MPStats нашел конкурентов, но не вернул по ним продажи и выручку. Такой список не используем для решения.</div>;
  }
  return (
    <div className="competitors">
      <strong>Топ конкурентов за период</strong>
      {competitors.map((competitor, index) => (
        <div key={`${competitor.nm_id ?? index}-${competitor.name ?? ""}`}>
          <span>{index + 1}. {competitor.name ?? "Без названия"}</span>
          <em>{formatEntityName(competitor.brand)} / {formatEntityName(competitor.supplier)}</em>
          <div className="competitor-metrics">
            <span>Цена <b>{formatMoney(competitor.price)}</b></span>
            <span>7д <b>{formatNumber(competitor.periods?.week?.sales)}</b> / <b>{formatMoney(competitor.periods?.week?.revenue)}</b></span>
            <span>30д <b>{formatNumber(competitor.periods?.month?.sales)}</b> / <b>{formatMoney(competitor.periods?.month?.revenue)}</b></span>
            <span>90д <b>{formatNumber(competitor.periods?.quarter?.sales)}</b> / <b>{formatMoney(competitor.periods?.quarter?.revenue)}</b></span>
            <span>YTD <b>{formatNumber(competitor.periods?.year_to_date?.sales)}</b> / <b>{formatMoney(competitor.periods?.year_to_date?.revenue)}</b></span>
            <span>Отзывы <b>{formatNumber(competitor.feedbacks)}</b></span>
            <span>Остаток <b>{formatNumber(competitor.stock)}</b></span>
            <span>{competitor.url ? <a href={competitor.url} target="_blank">Открыть WB</a> : competitor.nm_id ?? "нет данных"}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function hasAnyPeriodData(competitor: Competitor) {
  return ["week", "month", "quarter", "year_to_date"].some((period) => {
    const item = competitor.periods?.[period];
    return Number(item?.sales ?? 0) > 0 || Number(item?.revenue ?? 0) > 0;
  });
}

function competitorRevenue(competitor: Competitor) {
  return Number(
    competitor.periods?.year_to_date?.revenue ??
      competitor.periods?.quarter?.revenue ??
      competitor.periods?.month?.revenue ??
      competitor.revenue ??
      0,
  );
}

function analysisSummary(analysis: ProductAnalysis) {
  return `Анализ готов: ${analysis.competitor_count ?? 0} конкурентов, средняя цена ${formatMoney(analysis.market_price_avg)}, маржа ${formatPercent(analysis.margin_percent)}, оценка запуска ${analysis.launch_score ?? "нет данных"} из 100.`;
}

function formatMoney(value?: string | number | null) {
  if (value === null || value === undefined || value === "") {
    return "нет данных";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "нет данных";
  }
  return `${number.toFixed(0)} ₽`;
}

function formatNumber(value?: string | number | null) {
  if (value === null || value === undefined || value === "") {
    return "нет данных";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "нет данных";
  }
  return number.toLocaleString("ru-RU");
}

function formatPercent(value?: number | null) {
  return value === null || value === undefined ? "нет данных" : `${value.toFixed(1)}%`;
}

function formatPriceRange(analysis: ProductAnalysis) {
  if (!analysis.market_price_min && !analysis.market_price_avg && !analysis.market_price_max) {
    return "нет данных";
  }
  return `${formatMoney(analysis.market_price_min)} / ${formatMoney(analysis.market_price_avg)} / ${formatMoney(analysis.market_price_max)}`;
}

function recommendationReason(product: SupplierProduct) {
  const reasons = [
    product.status === "analyzed" ? "есть анализ MPStats" : null,
    product.launch_score ? `оценка запуска ${product.launch_score.toFixed(2)} из 100` : null,
    product.wholesale_price ? `закупка ${formatMoney(product.wholesale_price)}` : null,
    product.photo_urls.length || product.source_url ? "есть фото/ссылка Звезды" : "нет фото",
  ].filter(Boolean);
  return reasons.join(", ");
}

function WBCardDraftView({ draft }: { draft?: WBCardDraft }) {
  if (!draft) {
    return null;
  }
  return (
    <div className="card-draft">
      <strong>Черновик карточки WB</strong>
      <dl>
        <dt>Название</dt><dd>{draft.title ?? "нет"}</dd>
        <dt>Предмет</dt><dd>{draft.subject ?? "нет"}</dd>
        <dt>Артикул</dt><dd>{draft.vendor_code ?? "нет"}</dd>
        <dt>Штрихкод</dt><dd>{draft.barcode ?? "нет"}</dd>
        <dt>Цена</dt><dd>{formatMoney(draft.recommended_price)}</dd>
        <dt>Фото Звезды</dt><dd>{draft.source_images?.length ?? 0}</dd>
        <dt>Описание</dt><dd>{draft.description ?? "нет"}</dd>
      </dl>
      {draft.characteristics ? (
        <div className="characteristics">
          {Object.entries(draft.characteristics).map(([key, value]) => (
            <span key={key}>{key}: {String(value)}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function formatEntityName(value?: string | { name?: string | null } | null) {
  if (!value) {
    return "нет данных";
  }
  if (typeof value === "string") {
    return value;
  }
  return value.name ?? "нет данных";
}

function pageFromHash(hash: string): Page {
  const page = hash.replace("#", "");
  if (["price", "products", "analysis", "content", "settings"].includes(page)) {
    return page as Page;
  }
  return "price";
}

function formatProductStatus(status?: string | null) {
  const statuses: Record<string, string> = {
    new: "новый",
    missing_on_wb: "нет в продаже",
    listed: "в продаже",
    analysis_pending: "анализируется",
    analyzed: "проанализирован",
    content_pending: "контент в работе",
    content_ready: "контент готов",
    rejected: "отклонен",
  };
  return status ? statuses[status] ?? status : "нет статуса";
}

function formatJobStatus(status?: string | null) {
  const statuses: Record<string, string> = {
    queued: "в очереди",
    running: "в работе",
    processing: "в работе",
    in_progress: "в работе",
    completed: "готово",
    done: "готово",
    success: "готово",
    failed: "ошибка",
    error: "ошибка",
    partial: "частично готово",
  };
  return status ? statuses[status.toLowerCase()] ?? status : "нет статуса";
}

createRoot(document.getElementById("root")!).render(<App />);
