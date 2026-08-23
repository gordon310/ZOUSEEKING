create table if not exists public.query_field_options (
  id uuid primary key default gen_random_uuid(),
  option_type text not null,
  parent_value text not null default '',
  value text not null,
  label text not null default '',
  sort_order int not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(option_type, parent_value, value)
);

create index if not exists idx_field_options_type_parent
on public.query_field_options(option_type, parent_value, is_active, sort_order);

alter table public.query_field_options enable row level security;

drop policy if exists "public can read field options" on public.query_field_options;
create policy "public can read field options"
on public.query_field_options for select
to anon
using (is_active = true);

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'prefecture', '', value, value, ord::int, true
from unnest(array[
  '北海道','青森县','岩手县','宫城县','秋田县','山形县','福岛县','茨城县','栃木县','群马县','埼玉县','千叶县',
  '东京都','神奈川县','新潟县','富山县','石川县','福井县','山梨县','长野县','岐阜县','静冈县','爱知县','三重县',
  '滋贺县','京都府','大阪府','兵库县','奈良县','和歌山县','鸟取县','岛根县','冈山县','广岛县','山口县',
  '德岛县','香川县','爱媛县','高知县','福冈县','佐贺县','长崎县','熊本县','大分县','宫崎县','鹿儿岛县','冲绳县'
]) with ordinality as t(value, ord)
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'city', prefecture, city, city, row_number() over(order by prefecture, city)::int, true
from (values
  ('北海道','札幌市'),('青森县','青森市'),('岩手县','盛冈市'),('宫城县','仙台市'),('秋田县','秋田市'),('山形县','山形市'),
  ('福岛县','福岛市'),('茨城县','水户市'),('栃木县','宇都宫市'),('群马县','前桥市'),('埼玉县','埼玉市'),('千叶县','千叶市'),
  ('东京都','东京23区'),('神奈川县','横滨市'),('新潟县','新潟市'),('富山县','富山市'),('石川县','金泽市'),('福井县','福井市'),
  ('山梨县','甲府市'),('长野县','长野市'),('岐阜县','岐阜市'),('静冈县','静冈市'),('爱知县','名古屋市'),('三重县','津市'),
  ('滋贺县','大津市'),('京都府','京都市'),('大阪府','大阪市'),('兵库县','神户市'),('奈良县','奈良市'),('和歌山县','和歌山市'),
  ('鸟取县','鸟取市'),('岛根县','松江市'),('冈山县','冈山市'),('广岛县','广岛市'),('山口县','山口市'),('德岛县','德岛市'),
  ('香川县','高松市'),('爱媛县','松山市'),('高知县','高知市'),('福冈县','福冈市'),('佐贺县','佐贺市'),('长崎县','长崎市'),
  ('熊本县','熊本市'),('大分县','大分市'),('宫崎县','宫崎市'),('鹿儿岛县','鹿儿岛市'),('冲绳县','那霸市')
) as c(prefecture, city)
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'ward', parent_value, value, value, ord::int, true
from (
  select '东京都::东京23区' as parent_value, value, ord
  from unnest(array[
    '千代田区','中央区','港区','新宿区','文京区','台东区','墨田区','江东区','品川区','目黑区','大田区','世田谷区',
    '涩谷区','中野区','杉并区','丰岛区','北区','荒川区','板桥区','练马区','足立区','葛饰区','江户川区'
  ]) with ordinality as t(value, ord)
  union all
  select '大阪府::大阪市' as parent_value, value, ord
  from unnest(array[
    '北区','都岛区','福岛区','此花区','中央区','西区','港区','大正区','天王寺区','浪速区','西淀川区','淀川区',
    '东淀川区','东成区','生野区','旭区','城东区','鹤见区','阿倍野区','住之江区','住吉区','东住吉区','平野区','西成区'
  ]) with ordinality as t(value, ord)
  union all
  select '神奈川县::横滨市' as parent_value, value, ord
  from unnest(array[
    '鹤见区','神奈川区','西区','中区','南区','港南区','保土谷区','旭区','矶子区','金泽区','港北区','绿区',
    '青叶区','都筑区','户塚区','荣区','泉区','濑谷区'
  ]) with ordinality as t(value, ord)
) wards
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'asset_type', '', value, value, ord::int, true
from unnest(array['塔楼','公寓','一户建']) with ordinality as t(value, ord)
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'year', '', value, value, ord::int, true
from unnest(array['2024','2025','2026','2027']) with ordinality as t(value, ord)
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();

insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
select 'month', '', value, value || '月', ord::int, true
from unnest(array['1','2','3','4','5','6','7','8','9','10','11','12']) with ordinality as t(value, ord)
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();
