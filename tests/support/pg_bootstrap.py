"""Disposable PostgreSQL bootstrap used by real-database tests."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[Path, ...]:
    """Return every repository migration in filename order."""
    return tuple(sorted(migrations_dir.glob("*.sql")))


def database_url(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def is_local_server(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


BOOTSTRAP_SQL = """
do $$
begin
  if to_regrole('anon') is null then execute 'create role anon nologin'; end if;
  if to_regrole('authenticated') is null then execute 'create role authenticated nologin'; end if;
  if to_regrole('service_role') is null then execute 'create role service_role nologin'; end if;
end $$;
create schema if not exists auth;
create table if not exists auth.users (
  id uuid primary key,
  email text,
  raw_user_meta_data jsonb not null default '{}'::jsonb
);
create or replace function auth.uid() returns uuid
language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end
$$;
create or replace function public.is_service_role() returns boolean
language sql stable set search_path = public as $$
  select current_user in ('postgres', 'service_role', 'supabase_admin')
      or coalesce(current_setting('request.jwt.claim.role', true), '')
         in ('service_role', 'supabase_admin');
$$;
"""


async def apply_migrations(
    conn: asyncpg.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> None:
    """Apply the complete sorted repository migration history to a connection."""
    for path in discover_migrations(migrations_dir):
        await conn.execute(path.read_text(encoding="utf-8"))


async def bootstrap_and_migrate(url: str, database: str) -> None:
    """Recreate a disposable database and apply the complete migration history."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute(f"drop database if exists {database} with (force)")
        await admin.execute(f"create database {database}")
    finally:
        await admin.close()

    conn = await asyncpg.connect(database_url(url, database))
    try:
        await conn.execute(BOOTSTRAP_SQL)
        await apply_migrations(conn)
    finally:
        await conn.close()
