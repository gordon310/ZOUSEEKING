-- MLIT official transaction-price download rows.  This table stores the
-- source row and canonical numeric fields separately so analytics never parse
-- presentation strings or confuse estimates with observations.
update public.sources
set name='国土交通省 不動産情報ライブラリ（不動産価格）',
    url='https://www.reinfolib.mlit.go.jp/realEstatePrices/',
    source_type='government_open_data',
    permission_status='rights_confirmed',
    updated_at=now()
where id='bf4b6d56-f7ed-4e66-b599-3900e22001d6'::uuid;

create table if not exists public.mlit_transactions (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.sources(id) on delete restrict,
  source_record_key text not null,
  prefecture text not null,
  city text not null,
  ward text,
  asset_kind text not null,
  asset_type text not null check (asset_type in ('塔楼', '公寓', '独栋', '土地')),
  price_jpy numeric(18,0) check (price_jpy is null or price_jpy >= 0),
  area_sqm numeric(12,2) check (area_sqm is null or area_sqm > 0),
  unit_price_jpy_per_sqm numeric(18,2) check (unit_price_jpy_per_sqm is null or unit_price_jpy_per_sqm > 0),
  trade_quarter text not null check (trade_quarter ~ '^[0-9]{4}Q[1-4]$'),
  trade_year smallint not null check (trade_year between 2005 and 2200),
  nearest_station text,
  distance_minutes smallint check (distance_minutes is null or distance_minutes >= 0),
  layout text,
  raw jsonb not null,
  imported_at timestamptz not null default now(),
  constraint mlit_transactions_source_key_unique unique (source_id, source_record_key)
);

create index if not exists idx_mlit_transactions_region_period_type
  on public.mlit_transactions(prefecture, city, ward, asset_type, trade_year, trade_quarter);
create index if not exists idx_mlit_transactions_source on public.mlit_transactions(source_id);

alter table public.mlit_transactions enable row level security;
revoke all on public.mlit_transactions from anon, authenticated;
grant select on public.mlit_transactions to authenticated;
grant all privileges on public.mlit_transactions to service_role;
create policy "authenticated can read official MLIT transactions"
  on public.mlit_transactions for select to authenticated using (true);
