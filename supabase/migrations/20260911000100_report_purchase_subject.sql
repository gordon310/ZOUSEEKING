-- Report-scoped subject for one-time purchases.
-- Existing orders remain NULL and therefore do not unlock any report.
alter table public.payment_orders
  add column if not exists subject_id text;

create index if not exists idx_payment_orders_owner_product_subject_status
  on public.payment_orders(owner_user_id, product_code, subject_id, status);
