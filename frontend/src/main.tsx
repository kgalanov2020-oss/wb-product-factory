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

const DEFAULT_API_URL =
  import.meta.env.VITE_API_URL ?? "https://wb-product-factory-api.onrender.com";

type Integrations = {
  supabase: boolean;
  mpstats_login: boolean;
  aidentika: boolean;
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
  photo_urls: string[];
  source_url?: string | null;
  status: string;
  launch_score?: number | null;
};

type ProductListResponse = {
  products: SupplierProduct[];
  total: number;
};

type ContentJob = {
  job_id: string;
  status: string;
  product_name: string;
  actions: Array<{
    asset_type: string;
    action_id: number;
    status: string;
    result_url?: string | null;
    error_message?: string | null;
  }>;
};

function App() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [products, setProducts] = useState<SupplierProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<SupplierProduct | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sheetUrl, setSheetUrl] = useState("");
  const [message, setMessage] = useState("");
  const [jobs, setJobs] = useState<ContentJob[]>([]);
  const [loading, setLoading] = useState(false);

  const stats = useMemo(() => {
    const ready = jobs.filter((job) => job.status === "completed").length;
    const running = jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
    return {
      products: total,
      contentReady: ready,
      contentRunning: running,
      missing: products.filter((product) => product.status === "missing_on_wb").length,
    };
  }, [jobs, products, total]);

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
      const [health, productList] = await Promise.all([
        request<Integrations>("/api/v1/integrations/health"),
        request<ProductListResponse>("/api/v1/supplier-products?limit=100"),
      ]);
      setIntegrations(health);
      setProducts(productList.products);
      setTotal(productList.total);
      if (!selected && productList.products.length) {
        setSelected(productList.products[0]);
      }
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
      setMessage("Вставьте публичную CSV-ссылку Google Sheets.");
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
    const image = product.photo_urls[0];
    if (!image) {
      setMessage("У товара нет ссылки на фото.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const job = await request<ContentJob>("/api/v1/product-content/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_name: product.name,
          brand: "Звезда",
          images: [{ url: image }],
          assets: ["main_photo", "infographic", "advantages"],
          facts: [
            product.category ? `категория: ${product.category}` : "товар поставщика Звезда",
            product.wholesale_price ? `закупочная цена: ${product.wholesale_price}` : "цена требует проверки",
          ],
          target_audience: "покупатели Wildberries, товары для хобби и сборных моделей",
        }),
      });
      setJobs((current) => [job, ...current]);
      setMessage(`Запущена генерация: ${job.job_id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка генерации");
    } finally {
      setLoading(false);
    }
  }

  async function analyzeProduct(product: SupplierProduct) {
    setLoading(true);
    setMessage("");
    try {
      const analysis = await request<{ launch_score?: number | null; margin_percent?: number | null }>(
        `/api/v1/supplier-products/${product.id}/analyze`,
        { method: "POST" },
      );
      setMessage(
        `Анализ готов. Score: ${analysis.launch_score ?? "?"}, маржа: ${analysis.margin_percent?.toFixed(1) ?? "?"}%`,
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка анализа");
    } finally {
      setLoading(false);
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

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Boxes size={24} />
          <span>WB Factory</span>
        </div>
        <nav>
          <a href="#dashboard"><BarChart3 size={18} /> Dashboard</a>
          <a href="#import"><FileSpreadsheet size={18} /> Прайс</a>
          <a href="#products"><Search size={18} /> Товары</a>
          <a href="#content"><ImagePlus size={18} /> Контент</a>
          <a href="#settings"><Settings size={18} /> Интеграции</a>
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

        <section className="metrics" id="dashboard">
          <Metric label="Товаров в прайсе" value={stats.products} />
          <Metric label="Нет в продаже" value={stats.missing} />
          <Metric label="Контент в работе" value={stats.contentRunning} />
          <Metric label="Контент готов" value={stats.contentReady} />
        </section>

        <section className="panel" id="import">
          <div className="panel-title">
            <h2>Импорт прайса Звезда</h2>
            <span>CSV/XLSX или публичная CSV-ссылка Google Sheets</span>
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
              placeholder="https://docs.google.com/spreadsheets/.../export?format=csv"
            />
            <button onClick={importUrl} disabled={loading}>Импортировать URL</button>
          </div>
        </section>

        <section className="workspace">
          <div className="panel product-list" id="products">
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
              <span>{selected?.status ?? "status"}</span>
            </div>
            {selected ? (
              <>
                <div className="product-card">
                  {selected.photo_urls[0] ? <img src={selected.photo_urls[0]} alt={selected.name} /> : <div className="no-photo">Нет фото</div>}
                  <dl>
                    <dt>Артикул</dt><dd>{selected.sku ?? "не указан"}</dd>
                    <dt>Категория</dt><dd>{selected.category ?? "не указана"}</dd>
                    <dt>Закупка</dt><dd>{selected.wholesale_price ?? "не указана"}</dd>
                    <dt>Остаток</dt><dd>{selected.stock ?? "не указан"}</dd>
                  </dl>
                </div>
                <div className="actions">
                  <button onClick={() => analyzeProduct(selected)} disabled={loading}>MPStats-анализ</button>
                  <button onClick={() => generateContent(selected)} disabled={loading || !selected.photo_urls.length}>
                    Сгенерировать карточку
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </section>

        <section className="panel" id="content">
          <div className="panel-title">
            <h2>Генерации контента</h2>
            <span>Aidentika jobs</span>
          </div>
          <div className="jobs">
            {jobs.map((job) => (
              <article className="job" key={job.job_id}>
                <div>
                  <strong>{job.product_name}</strong>
                  <span>{job.status}</span>
                </div>
                <button onClick={() => syncJob(job.job_id)} disabled={loading}>Обновить</button>
                <div className="job-actions">
                  {job.actions.map((action) => (
                    <div key={action.action_id}>
                      <span>{action.asset_type}</span>
                      <em>{action.status}</em>
                      {action.result_url ? <a href={action.result_url} target="_blank">Открыть</a> : null}
                    </div>
                  ))}
                </div>
              </article>
            ))}
            {!jobs.length ? <div className="empty">Задач генерации пока нет.</div> : null}
          </div>
        </section>

        <section className="panel" id="settings">
          <div className="panel-title">
            <h2>Интеграции</h2>
            <span>Render API</span>
          </div>
          <input value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} />
          <div className="status-grid">
            <Status label="Supabase" ok={integrations?.supabase} />
            <Status label="MPStats" ok={integrations?.mpstats_login} />
            <Status label="Aidentika" ok={integrations?.aidentika} />
          </div>
        </section>
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

createRoot(document.getElementById("root")!).render(<App />);
