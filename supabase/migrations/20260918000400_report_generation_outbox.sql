-- Durable report-generation outbox. FastAPI inserts/resets this row in the
-- same transaction as the query/job; only the service worker can mutate it.
create table if not exists public.report_generation_outbox (
  id uuid primary key default gen_random_uuid(),
  generation_job_id uuid not null references public.generation_jobs(id) on delete cascade,
  query_id uuid not null references public.queries(id) on delete cascade,
  idempotency_key text not null unique,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'retryable', 'completed', 'failed')),
  attempts integer not null default 0 check (attempts >= 0 and attempts <= 3),
  max_attempts integer not null default 3 check (max_attempts between 1 and 3),
  next_attempt_at timestamptz not null default now(),
  claim_token uuid,
  claimed_at timestamptz,
  completed_at timestamptz,
  last_error_code text,
  last_error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (generation_job_id)
);

create index if not exists idx_report_generation_outbox_due
  on public.report_generation_outbox(status, next_attempt_at, created_at);
create index if not exists idx_report_generation_outbox_query
  on public.report_generation_outbox(query_id, status);

drop trigger if exists set_report_generation_outbox_updated_at on public.report_generation_outbox;
create trigger set_report_generation_outbox_updated_at
before update on public.report_generation_outbox
for each row execute function public.set_updated_at();

alter table public.report_generation_outbox enable row level security;
revoke all on public.report_generation_outbox from public, anon, authenticated;
grant select, insert, update, delete on public.report_generation_outbox to service_role;

comment on table public.report_generation_outbox is
  '唯一报告长任务投递表；FastAPI transactionally enqueues, one durable worker claims and executes.';
comment on column public.report_generation_outbox.last_error_code is
  'Safe classified error code only; raw exception text never crosses the public job API.';
