create extension if not exists pgcrypto;

create table if not exists public.mpstats_collections (
  id bigserial primary key,
  query text not null,
  collected_at timestamptz not null,
  niches jsonb not null default '[]'::jsonb,
  competitors jsonb not null default '[]'::jsonb,
  sales jsonb not null default '[]'::jsonb,
  prices jsonb not null default '[]'::jsonb,
  revenue jsonb not null default '[]'::jsonb,
  raw_payloads jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_mpstats_collections_query
  on public.mpstats_collections (query);

create index if not exists idx_mpstats_collections_collected_at
  on public.mpstats_collections (collected_at desc);

create table if not exists public.product_content_jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'completed', 'failed', 'partial')),
  product_name text not null,
  request_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_product_content_jobs_status
  on public.product_content_jobs (status);

create index if not exists idx_product_content_jobs_created_at
  on public.product_content_jobs (created_at desc);

create table if not exists public.product_content_actions (
  id bigserial primary key,
  job_id uuid not null references public.product_content_jobs(id) on delete cascade,
  asset_type text not null
    check (asset_type in ('main_photo', 'infographic', 'advantages', 'usage', 'comparison')),
  aidentika_action_id bigint not null,
  status text not null,
  poll_url text,
  result_url text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (job_id, aidentika_action_id)
);

create index if not exists idx_product_content_actions_job_id
  on public.product_content_actions (job_id);

create index if not exists idx_product_content_actions_aidentika_action_id
  on public.product_content_actions (aidentika_action_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_product_content_jobs_updated_at on public.product_content_jobs;
create trigger set_product_content_jobs_updated_at
before update on public.product_content_jobs
for each row execute function public.set_updated_at();

drop trigger if exists set_product_content_actions_updated_at on public.product_content_actions;
create trigger set_product_content_actions_updated_at
before update on public.product_content_actions
for each row execute function public.set_updated_at();

create table if not exists public.supplier_products (
  id uuid primary key default gen_random_uuid(),
  supplier text not null default 'zvezda',
  sku text,
  barcode text,
  name text not null,
  category text,
  wholesale_price numeric,
  retail_price numeric,
  stock integer,
  pack_units integer,
  weight_grams numeric,
  dimensions text,
  description text,
  order_quantity integer,
  photo_urls jsonb not null default '[]'::jsonb,
  source_url text,
  status text not null default 'new'
    check (status in (
      'new',
      'missing_on_wb',
      'listed',
      'analysis_pending',
      'analyzed',
      'content_pending',
      'content_ready',
      'rejected'
    )),
  launch_score numeric,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (supplier, sku)
);

create index if not exists idx_supplier_products_supplier
  on public.supplier_products (supplier);

create index if not exists idx_supplier_products_status
  on public.supplier_products (status);

create index if not exists idx_supplier_products_launch_score
  on public.supplier_products (launch_score desc nulls last);

alter table public.supplier_products
  add column if not exists pack_units integer,
  add column if not exists weight_grams numeric,
  add column if not exists dimensions text,
  add column if not exists description text,
  add column if not exists order_quantity integer;

create table if not exists public.wb_card_mappings (
  id bigserial primary key,
  mapping_key text not null unique,
  supplier text not null default 'zvezda',
  manufacturer_article text,
  seller_article text,
  wb_article text,
  barcode text,
  brand text,
  subject text,
  name text,
  purchase_price numeric,
  retail_price numeric,
  pack_units integer,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_wb_card_mappings_supplier
  on public.wb_card_mappings (supplier);

create index if not exists idx_wb_card_mappings_manufacturer_article
  on public.wb_card_mappings (manufacturer_article);

create index if not exists idx_wb_card_mappings_wb_article
  on public.wb_card_mappings (wb_article);

create index if not exists idx_wb_card_mappings_seller_article
  on public.wb_card_mappings (seller_article);

create table if not exists public.wb_stock_snapshots (
  id bigserial primary key,
  captured_at timestamptz not null default now(),
  wb_article text not null,
  seller_article text,
  brand text,
  subject text,
  stock_qty integer not null default 0,
  in_way_to_client integer not null default 0,
  in_way_from_client integer not null default 0,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_wb_stock_snapshots_wb_article
  on public.wb_stock_snapshots (wb_article);

create index if not exists idx_wb_stock_snapshots_seller_article
  on public.wb_stock_snapshots (seller_article);

create index if not exists idx_wb_stock_snapshots_captured_at
  on public.wb_stock_snapshots (captured_at desc);

create or replace function public.normalize_article(value text)
returns text
language sql
immutable
as $$
  select regexp_replace(lower(coalesce(value, '')), '\s+', '', 'g');
$$;

create or replace function public.refresh_supplier_product_statuses(supplier_arg text default 'zvezda')
returns void
language plpgsql
as $$
begin
  update public.supplier_products product
  set status = 'listed'
  where product.supplier = supplier_arg
    and product.status in ('new', 'missing_on_wb', 'listed')
    and exists (
      select 1
      from public.wb_card_mappings mapping
      where mapping.supplier = supplier_arg
        and (
          public.normalize_article(mapping.manufacturer_article) = public.normalize_article(product.sku)
          or (product.barcode is not null and mapping.barcode = product.barcode)
        )
    );

  update public.supplier_products product
  set status = 'missing_on_wb'
  where product.supplier = supplier_arg
    and product.status in ('new', 'missing_on_wb', 'listed')
    and not exists (
      select 1
      from public.wb_card_mappings mapping
      where mapping.supplier = supplier_arg
        and (
          public.normalize_article(mapping.manufacturer_article) = public.normalize_article(product.sku)
          or (product.barcode is not null and mapping.barcode = product.barcode)
        )
    );
end;
$$;

create table if not exists public.product_analyses (
  product_id uuid primary key references public.supplier_products(id) on delete cascade,
  status text not null default 'pending'
    check (status in ('pending', 'completed', 'failed')),
  market_price_min numeric,
  market_price_avg numeric,
  market_price_max numeric,
  competitor_count integer,
  estimated_sales integer,
  estimated_revenue numeric,
  margin_percent numeric,
  launch_score numeric,
  notes text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_supplier_products_updated_at on public.supplier_products;
create trigger set_supplier_products_updated_at
before update on public.supplier_products
for each row execute function public.set_updated_at();

drop trigger if exists set_product_analyses_updated_at on public.product_analyses;
create trigger set_product_analyses_updated_at
before update on public.product_analyses
for each row execute function public.set_updated_at();

drop trigger if exists set_wb_card_mappings_updated_at on public.wb_card_mappings;
create trigger set_wb_card_mappings_updated_at
before update on public.wb_card_mappings
for each row execute function public.set_updated_at();

alter table public.mpstats_collections enable row level security;
alter table public.product_content_jobs enable row level security;
alter table public.product_content_actions enable row level security;
alter table public.supplier_products enable row level security;
alter table public.wb_card_mappings enable row level security;
alter table public.wb_stock_snapshots enable row level security;
alter table public.product_analyses enable row level security;
