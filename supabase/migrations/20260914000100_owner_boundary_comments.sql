-- Forward-only ownership boundary documentation.
-- Do not remove or rename the legacy requested_by_* columns: existing data is
-- frozen. They are display metadata only and never an authorization input.

comment on column public.queries.owner_user_id is
  '唯一归属与授权边界；必须绑定 auth.uid()。不得使用 requested_by_name/email 做授权。';

comment on column public.queries.requested_by_name is
  '历史展示元数据；仅展示用途，禁止作为归属或授权判断输入。';

comment on column public.queries.requested_by_email is
  '历史展示元数据；仅展示用途，禁止作为归属或授权判断输入。';
