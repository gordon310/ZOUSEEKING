-- Disposable-local assertions for V1 provenance, policy-version exclusion,
-- source-rights enforcement, and append-only analysis metrics.
do $$
declare required_column text;
begin
  foreach required_column in array array[
    'data_class', 'source_period', 'observed_at', 'transformation_version',
    'limitations', 'permission_status'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'sources'
        and column_name = required_column
    ) then
      raise exception 'sources provenance column missing: %', required_column;
    end if;
    if exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'sources'
        and column_name = required_column
        and is_nullable <> 'NO'
    ) then
      raise exception 'sources provenance column must be NOT NULL: %', required_column;
    end if;
  end loop;

  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'sources'
      and column_name = 'permission_status'
      and column_default is not null
  ) then
    raise exception 'sources permission_status must not fabricate a default';
  end if;

  foreach required_column in array array[
    'data_class', 'source_url', 'source_locator', 'source_period', 'observed_at',
    'transformation_version', 'report_version', 'limitations', 'report_status',
    'source_id'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'property_reports'
        and column_name = required_column
    ) then
      raise exception 'property_reports provenance column missing: %', required_column;
    end if;
  end loop;

  foreach required_column in array array[
    'data_class', 'source_id', 'source_locator', 'source_period', 'observed_at',
    'report_version', 'limitations', 'report_status'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'analysis_metrics'
        and column_name = required_column
    ) then
      raise exception 'analysis_metrics provenance column missing: %', required_column;
    end if;
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'risk_findings'
        and column_name = required_column
    ) then
      raise exception 'risk_findings provenance column missing: %', required_column;
    end if;
  end loop;

  if not exists (
    select 1 from pg_constraint
    where conname = 'policy_documents_no_overlapping_versions'
      and conrelid = 'public.policy_documents'::regclass
      and contype = 'x'
  ) then
    raise exception 'policy exclusion constraint is missing';
  end if;
end $$;

begin;
do $$
declare
  synthetic_source_id uuid;
  restricted_source_id uuid;
  confirmed_source_id uuid;
  user_confirmed_source_id uuid;
  user_restricted_source_id uuid;
  property_id uuid;
  metric_id uuid;
  rejected boolean;
begin
  begin
    insert into public.sources(
      name, source_type, url, permission_status, data_class, source_period,
      observed_at, transformation_version, limitations
    ) values (
      'invalid permission fixture', 'fixture',
      'https://example.invalid/invalid-rights', 'unknown',
      'synthetic_fixture', '2026-08', now(), 'fixture-v1', 'assertion only'
    );
    raise exception 'invalid permission status was accepted';
  exception when check_violation then null;
  end;

  rejected := false;
  begin
    insert into public.property_reports(
      query_key, slug, title, publish_month, report_status
    ) values (
      'missing-provenance-report', 'missing-provenance-report',
      'assertion', '2026-08', 'full_report'
    );
  exception when check_violation or raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'published report without provenance was accepted';
  end if;

  insert into public.sources(
    name, source_type, url, permission_status, data_class, source_period,
    observed_at, transformation_version, limitations
  ) values (
    'user confirmed fixture', 'submission',
    'https://example.invalid/user-confirmed', 'rights_confirmed',
    'user_submitted', '2026-08', now(), 'submission-v1', 'assertion only'
  ) returning id into user_confirmed_source_id;

  insert into public.property_reports(
    query_key, slug, title, publish_month, report_status, data_class,
    source_id, source_locator, source_period, observed_at,
    transformation_version, report_version, limitations
  ) values (
    'user-confirmed-report', 'user-confirmed-report', 'assertion', '2026-08',
    'full_report', 'user_submitted', user_confirmed_source_id,
    'submission:assertion', '2026-08', now(), 'submission-v1', 'v1',
    'assertion only'
  );

  rejected := false;
  begin
    insert into public.property_reports(
      query_key, slug, title, publish_month, report_status, data_class,
      source_locator, source_period, observed_at, transformation_version,
      report_version, limitations
    ) values (
      'user-without-source-report', 'user-without-source-report',
      'assertion', '2026-08', 'full_report', 'user_submitted',
      'submission:assertion', '2026-08', now(), 'submission-v1', 'v1',
      'assertion only'
    );
  exception when check_violation or raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'published user-submitted report without source was accepted';
  end if;

  insert into public.sources(
    name, source_type, url, permission_status, data_class, source_period,
    observed_at, transformation_version, limitations
  ) values (
    'user restricted fixture', 'submission',
    'https://example.invalid/user-restricted', 'rights_restricted',
    'user_submitted', '2026-08', now(), 'submission-v1', 'assertion only'
  ) returning id into user_restricted_source_id;

  rejected := false;
  begin
    insert into public.property_reports(
      query_key, slug, title, publish_month, report_status, data_class,
      source_id, source_locator, source_period, observed_at,
      transformation_version, report_version, limitations
    ) values (
      'user-restricted-report', 'user-restricted-report', 'assertion',
      '2026-08', 'full_report', 'user_submitted', user_restricted_source_id,
      'submission:assertion', '2026-08', now(), 'submission-v1', 'v1',
      'assertion only'
    );
  exception when check_violation or raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'published user-submitted report accepted a restricted source';
  end if;

  insert into public.policy_documents(
    policy_key, title, jurisdiction, authority, source_url,
    effective_from, effective_to
  ) values (
    'assertion-policy', 'first', 'JP', 'fixture',
    'https://example.invalid/policy', date '2026-01-01', date '2026-05-31'
  );
  insert into public.policy_documents(
    policy_key, title, jurisdiction, authority, source_url, effective_from
  ) values (
    'assertion-policy', 'second', 'JP', 'fixture',
    'https://example.invalid/policy-2', date '2026-06-01'
  );
  begin
    insert into public.policy_documents(
      policy_key, title, jurisdiction, authority, source_url, effective_from
    ) values (
      'assertion-policy', 'overlap', 'JP', 'fixture',
      'https://example.invalid/policy-overlap', date '2026-07-01'
    );
    raise exception 'overlapping policy versions were accepted';
  exception when exclusion_violation then null;
  end;

  insert into public.sources(
    name, source_type, url, permission_status, data_class, source_period,
    observed_at, transformation_version, limitations
  ) values (
    'synthetic metric fixture', 'fixture',
    'https://example.invalid/metric', 'rights_confirmed',
    'synthetic_fixture', '2026-08', now(), 'fixture-v1', 'assertion only'
  ) returning id into synthetic_source_id;

  insert into public.sources(
    name, source_type, url, permission_status, data_class, source_period,
    observed_at, transformation_version, limitations
  ) values (
    'restricted aggregate fixture', 'aggregate',
    'https://example.invalid/restricted', 'rights_restricted',
    'scraped_aggregate', '2026-08', now(), 'aggregate-v1', 'assertion only'
  ) returning id into restricted_source_id;

  rejected := false;
  begin
    insert into public.property_reports(
      query_key, slug, title, publish_month, report_status, data_class,
      source_id, source_period, observed_at, transformation_version,
      report_version, limitations
    ) values (
      'restricted-report', 'restricted-report', 'assertion', '2026-08',
      'full_report', 'scraped_aggregate', restricted_source_id, '2026-08',
      now(), 'aggregate-v1', 'v1', 'assertion only'
    );
  exception when check_violation or raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'published report accepted a restricted source';
  end if;

  insert into public.sources(
    name, source_type, url, permission_status, data_class, source_period,
    observed_at, transformation_version, limitations
  ) values (
    'confirmed aggregate fixture', 'aggregate',
    'https://example.invalid/confirmed', 'rights_confirmed',
    'scraped_aggregate', '2026-08', now(), 'aggregate-v1', 'assertion only'
  ) returning id into confirmed_source_id;

  insert into public.property_reports(
    query_key, slug, title, publish_month, report_status, data_class,
    source_id, source_period, observed_at, transformation_version,
    report_version, limitations
  ) values (
    'confirmed-report', 'confirmed-report', 'assertion', '2026-08',
    'full_report', 'scraped_aggregate', confirmed_source_id, '2026-08',
    now(), 'aggregate-v1', 'v1', 'assertion only'
  );

  insert into public.properties(project_type, data_class, source_id)
  values ('residential', 'synthetic_fixture', synthetic_source_id)
  returning id into property_id;
  insert into public.analysis_metrics(
    property_id, metric_name, unit, calculation_version
  ) values (property_id, 'assertion_metric', 'JPY', 'assertion-v1')
  returning id into metric_id;

  rejected := false;
  begin
    update public.analysis_metrics set metric_value = 1 where id = metric_id;
  exception when raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'analysis metric update was accepted';
  end if;

  rejected := false;
  begin
    delete from public.analysis_metrics where id = metric_id;
  exception when raise_exception then rejected := true;
  end;
  if not rejected then
    raise exception using errcode = 'P0002',
      message = 'analysis metric delete was accepted';
  end if;
end;
$$;
rollback;
