-- Intake renovation observations: optional user-asserted interior condition
-- rows feeding the free-preview renovation estimate snapshot.
alter table public.analysis_sessions
  add column if not exists asset_type text
  check (asset_type is null or asset_type in ('apartment', 'tower', 'detached_house', 'other'));

create table if not exists public.renovation_observations (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  room text not null,
  component text not null,
  condition text not null default 'unknown',
  scope text not null default 'unknown',
  quantity numeric not null default 1 check (quantity > 0),
  area_m2 numeric check (area_m2 is null or area_m2 > 0),
  notes text not null default '',
  evidence_input_id uuid references public.project_inputs(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint renovation_observations_room_allowed check (room in (
    'exterior', 'bathroom', 'kitchen', 'living_room', 'bedroom', 'balcony'
  )),
  constraint renovation_observations_component_allowed check (component in (
    'unit_bath', 'wallpaper', 'flooring', 'kitchen', 'toilet', 'washstand', 'tatami'
  )),
  constraint renovation_observations_condition_allowed check (condition in (
    'new', 'good', 'aged', 'worn', 'stained', 'damaged',
    'mold_or_stain', 'water_damage_suspected', 'unknown'
  )),
  constraint renovation_observations_scope_allowed check (scope in (
    'replace', 'surface_refresh', 'repair', 'monitor', 'unknown'
  )),
  constraint renovation_observations_unique_scope unique (session_id, room, component)
);

create index if not exists idx_renovation_observations_session
  on public.renovation_observations(session_id, room);

alter table public.renovation_observations enable row level security;

revoke all on public.renovation_observations from anon, authenticated;

drop trigger if exists set_renovation_observations_updated_at on public.renovation_observations;
create trigger set_renovation_observations_updated_at
before update on public.renovation_observations
for each row execute function public.set_intake_updated_at();

alter table public.free_previews
  add column if not exists renovation_estimate jsonb;
