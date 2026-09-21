-- A source-owned license label is published with derived regional statistics.
-- Nullable preserves historic rows; the response contract deliberately rejects
-- a missing value rather than substituting a presentation literal.
alter table public.sources add column if not exists license text;

comment on column public.sources.license is
  'Source-provided license or reuse label published with derived statistics; NULL is a provenance error, never a display fallback.';
