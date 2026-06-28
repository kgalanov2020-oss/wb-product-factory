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
