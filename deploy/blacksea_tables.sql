-- Supabase tables for the @blacksea brand account.
-- Mirrors the tala_* schema exactly (see store.py). All access uses the
-- service_role key, which bypasses RLS, so no policies are needed.
-- Apply once in the Supabase SQL editor (or via the MCP apply_migration).

create table if not exists public.blacksea_posts (
  id              bigint generated always as identity primary key,
  topic           text not null,
  format          text default 'auto',
  text            text not null,
  status          text default 'draft',
  threads_post_id text,
  permalink       text,
  created_at      timestamptz not null default now(),
  published_at    timestamptz
);

create table if not exists public.blacksea_token (
  id           integer primary key default 1 check (id = 1),
  access_token text not null,
  expires_at   timestamptz not null,
  updated_at   timestamptz not null default now()
);

create table if not exists public.blacksea_signals (
  id         bigint generated always as identity primary key,
  kind       text not null,
  keyword    text,
  source     text,
  text       text not null,
  url        text,
  likes      integer default 0,
  scraped_at timestamptz not null default now()
);

alter table public.blacksea_posts   enable row level security;
alter table public.blacksea_token   enable row level security;
alter table public.blacksea_signals enable row level security;
