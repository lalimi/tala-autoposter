-- Queue of other people's posts to reply to (the commenting feature).
-- Populated by scripts/refresh_signals.py (keyword scrape), consumed by
-- /api/comment (or `python main.py --comment`). thread_id is the Threads media
-- id used as reply_to_id; UNIQUE so re-scraping never duplicates or resets a
-- row we already commented on. Service_role bypasses RLS.
-- One table per brand: tala_comment_targets (blacksea not commenting for now).

create table if not exists public.tala_comment_targets (
  id            bigint generated always as identity primary key,
  thread_id     text not null unique,
  username      text,
  text          text not null,
  url           text,
  likes         integer default 0,
  keyword       text,
  status        text default 'new',   -- new | commented | failed
  reply_post_id text,
  reply_text    text,
  created_at    timestamptz not null default now(),
  commented_at  timestamptz
);

alter table public.tala_comment_targets enable row level security;
