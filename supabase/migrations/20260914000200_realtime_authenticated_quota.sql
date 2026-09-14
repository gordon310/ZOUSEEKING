-- Additive lookup acceleration for the transactional quota helper.
-- This migration intentionally does not alter existing columns, constraints,
-- policies, functions, triggers, or rows.
create index if not exists idx_plan_entitlements_live_effective
  on public.plan_entitlements(plan_code, metric, period, effective_from desc, created_at desc)
  where active = true;

