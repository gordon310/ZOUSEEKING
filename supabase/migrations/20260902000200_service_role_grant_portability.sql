-- Keep the trusted worker contract deterministic across Supabase CLI versions.
-- Some disposable stacks do not apply the managed-platform service_role grants.

grant all privileges on table
  public.queries,
  public.query_field_options,
  public.generation_jobs,
  public.property_reports,
  public.data_sources,
  public.user_profiles,
  public.sources,
  public.properties,
  public.residential_details,
  public.new_build_details,
  public.commercial_investment_details,
  public.evidences,
  public.analysis_metrics,
  public.risk_findings,
  public.policy_documents,
  public.product_events,
  public.analysis_sessions,
  public.project_inputs,
  public.project_field_evidence,
  public.project_fields,
  public.free_previews,
  public.intake_rate_limits
to service_role;
