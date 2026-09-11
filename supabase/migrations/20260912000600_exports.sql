-- Authenticated B-end report exports. Apply only through the reviewed migration workflow.

create table if not exists public.exports (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  status text not null check (status in ('completed', 'failed')),
  row_count integer not null check (row_count > 0),
  csv_content bytea not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_exports_owner_created
  on public.exports(owner_user_id, created_at desc);

alter table public.exports enable row level security;
revoke all on public.exports from public, anon, authenticated;
grant all on public.exports to service_role;

drop policy if exists "owners can read own exports" on public.exports;
create policy "owners can read own exports"
on public.exports for select to authenticated
using (owner_user_id = auth.uid() or public.is_service_role());
