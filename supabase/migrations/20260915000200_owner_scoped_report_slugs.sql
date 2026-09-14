-- Reports are private to an owner. The legacy global slug constraint caused
-- the same location query from a second account to fail at report insert time.
alter table public.property_reports
  drop constraint if exists property_reports_slug_key;

-- The query-level uniqueness remains authoritative and is intentionally not
-- changed: one owner/query still has at most one report row.
drop index if exists public.idx_reports_slug;
create unique index if not exists uq_property_reports_owner_slug
  on public.property_reports(owner_user_id, slug);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.property_reports'::regclass
      and conname = 'uq_property_reports_owner_slug'
  ) then
    alter table public.property_reports
      add constraint uq_property_reports_owner_slug
      unique using index uq_property_reports_owner_slug;
  end if;
end
$$;
