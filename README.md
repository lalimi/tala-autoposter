# Tala Autonomous Threads Autoposter

A 4-agent Python pipeline that researches, writes, and publishes Threads posts.
The same pipeline drives multiple accounts ("brands"), each with its own voice,
topics, Supabase tables, Threads token, and cron endpoint:

| Brand | Account | Voice | Cadence | Endpoint |
|---|---|---|---|---|
| `tala` | **@tala.sav** | personal, anxious-but-systemized, all-lowercase | every 2h | `/api/cron` |
| `blacksea` | **@blacksea** | friendly-businesslike platform voice, no hype | 3-4×/day | `/api/blacksea` |

```
MemoryAgent → ParserAgent → WriterAgent → MemoryAgent → PublisherAgent
(pick topic)   (research)     (write post)   (save draft)   (publish to Threads)
```

Everything brand-specific lives in `config/brands.py` (a `Brand` is threaded
through the pipeline and every agent). Adding a third account = one entry there
+ a topics file + an env token + three Supabase tables — no agent code changes.

**Cadence is self-throttling.** GitHub's scheduled crons are unreliable (they
delay and silently drop runs at the top of the hour), so each workflow fires
every 30 min and the endpoint *decides* whether to post: it skips unless the
last post is older than the brand's `min_gap_minutes` (`POST_MIN_GAP_MINUTES` ≈
2h for tala, `BLACKSEA_MIN_GAP_MINUTES` ≈ 3.5h for blacksea). A dropped/late run
is simply caught by the next slot, so the average cadence holds. Manual runs
(`main.py`, the "Run workflow" button) are never throttled.

| Agent | File | Job |
|---|---|---|
| ParserAgent | `agents/parser_agent.py` | gather raw signals into a ResearchBrief (does not write) |
| WriterAgent | `agents/writer_agent.py` | write one post in Tala's voice (Claude) |
| MemoryAgent | `agents/memory_agent.py` | SQLite state: topic rotation + post history |
| PublisherAgent | `agents/publisher_agent.py` | publish via Postiz public API |

## Setup

```bash
git clone <this repo> && cd tala-autoposter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in the keys (see below)
```

Requires **Python 3.11+** (`sqlite3` ships with the stdlib).

### `.env`

```
ANTHROPIC_API_KEY=sk-ant-...
WRITER_MODEL=claude-sonnet-4-20250514   # swap to a newer Sonnet here, no code change
POSTIZ_URL=http://localhost:3000
POSTIZ_API_KEY=...
POSTIZ_INTEGRATION_ID=...
POST_INTERVAL_HOURS=1
LOG_LEVEL=INFO
```

### Getting the Postiz API key

In Postiz: **Settings → Public API** → generate a key. Use it raw as `POSTIZ_API_KEY`.

> **Note (verified against Postiz source).** The public API is `POST /public/v1/posts`
> (not `/api/posts`), and the `Authorization` header is the **raw key** — *not*
> `Bearer <key>`. `PublisherAgent` already does this correctly.

### Getting `POSTIZ_INTEGRATION_ID`

Connect the Threads channel in the Postiz dashboard first, then list integrations:

```bash
curl -s http://localhost:3000/public/v1/integrations \
  -H "Authorization: $POSTIZ_API_KEY" | python3 -m json.tool
```

Copy the `id` of the Threads channel into `POSTIZ_INTEGRATION_ID`.

## Usage

```bash
python main.py                       # start the scheduler for @tala.sav (every POST_INTERVAL_HOURS)
python main.py --test                # run once, print the post, DO NOT publish
python main.py --dry-run             # run pipeline, print the post, skip publishing
python main.py --publish             # run once and PUBLISH for real
python main.py --stats               # print the last 10 posts (topic + status)

# Any command takes --brand to target another account:
python main.py --brand blacksea --test
python main.py --brand blacksea --publish
python main.py --brand blacksea --stats
```

On first run `data/memory.db` is auto-created and `topic_rotation` is seeded from
`config/topics.json`. Logs rotate daily into `logs/autoposter.log.YYYY-MM-DD`.

> `--test` / `--dry-run` still pick a topic (bumps rotation) and write a `draft` row, so
> they touch `memory.db`. Delete `data/memory.db` to reset.

## Brands: the @blacksea account

`blacksea` is the marketplace's own brand account. Same pipeline, different
`Brand` (`config/brands.py`): a calm, friendly-businesslike voice that posts
something useful 3-4×/day — platform features, getting authors to upload their
first product, helping buyers find what they need — without hype or clickbait.
Its rotation lives in `config/blacksea_topics.json`, and it leans on single
posts (occasional short tips chains) via `BLACKSEA_CHAIN_PROBABILITY` (default
0.2). It has no scraper: its posts are evergreen, so `blacksea_signals` stays
empty and the writer works from the topic + angle alone.

**One-time setup:**

1. **Supabase tables** — run `deploy/blacksea_tables.sql` once (mirrors the
   `tala_*` schema): `blacksea_posts`, `blacksea_token`, `blacksea_signals`.
2. **Token** — set `BLACKSEA_THREADS_ACCESS_TOKEN` (a long-lived Threads token
   for the @blacksea account) on Vercel. It's a first-run seed only; afterwards
   it lives in `blacksea_token` and auto-refreshes like Tala's.
3. **Cron** — `.github/workflows/blacksea-cron.yml` hits `/api/blacksea` 4×/day.
   It reuses Tala's existing `VERCEL_CRON_URL` and `CRON_SECRET` secrets (same
   Vercel project/domain, just a different route), so there's **no new secret to
   add** — it just works once the branch is deployed.

Test it before wiring the cron:

```bash
python main.py --brand blacksea --test     # generate, print, don't publish
python main.py --brand blacksea --publish  # publish one post for real
```

## Commenting (tala replies under other people's posts)

Besides publishing, tala can **reply under other people's posts** found by
keyword — a separate "comment" tick:

```
scraper (keyword search) → tala_comment_targets → CommentAgent → reply_to_id → Threads
```

- **Discovery** is the scraper's job (no browser on Vercel): `scripts/refresh_signals.py`
  now also queues keyword posts (with their Threads media id) into
  `tala_comment_targets` (run `deploy/comment_targets.sql` once). Keep the
  scraper running or the queue dries up and every tick is a no-op.
- **Replying**: `pipeline.run_comment()` picks the freshest un-commented
  candidate, writes a short, relevant, no-pitch reply in Tala's voice, and posts
  it via the Threads API `reply_to_id`. It self-throttles on
  `COMMENT_MIN_GAP_MINUTES` (~90 min) and skips when the queue is empty.
- **Trigger**: endpoint `/api/comment` (GitHub Actions `comment-cron.yml`, reuses
  `VERCEL_CRON_URL`/`CRON_SECRET`), or locally/VPS: `python main.py --comment`
  (`--comment --dry-run` to preview without posting).

> Only `tala` comments (`comments_enabled` in `config/brands.py`). Replying to
> strangers is rate-limited by design and kept non-spammy — no links, no CTA.
> Whether the Threads API accepts a reply to a *scraped* post id depends on the
> token's permissions and the target's reply settings; verify with one live tick.

## Metrics & light learning

Each post's Threads insights (views/likes/replies/reposts/quotes) are pulled
~24h after publishing (`run_metrics` / `--metrics`, hourly timer) and stored on
the post row. The writer then learns lightly: it's fed the **best-performing**
recent post (by views) as a style reference, plus the **last ~12 posts** with an
instruction not to repeat stories, details, or phrasing (dedup). Keyword pools
are broadened — `config/topics.json` for what Tala writes about, and
`config/comment_keywords.json` (general/everyday/humour) for what she comments
under, so comments aren't only about digital products.

## Plugging in the real parser

`parser/scraper.py` is a **placeholder** returning mock signals so the pipeline runs out
of the box. Replace the file with Tala's real parser, keeping this exact signature:

```python
def fetch_posts(keywords: list[str]) -> list[dict]:
    # -> [{"text": str, "source": str, "url": str, "keyword": str}, ...]
```

Nothing else needs to change.

## Run on a VPS with systemd (Hetzner etc.) — recommended

A VPS gives reliable timers (no GitHub-cron drops) and runs the scraper natively
(so commenting is self-contained). It replaces both Vercel and the GitHub
workflows — `main.py` does everything via `--tick`.

```bash
# on the server (SSH in from your Mac for easy paste). Private repo -> put a
# GitHub token in the clone URL. Two commands, then answer 3 prompts:
sudo git clone -b claude/blacksea-posting-agent-kxmbp \
  https://<GITHUB_TOKEN>@github.com/lalimi/tala-autoposter.git /opt/tala-autoposter

cd /opt/tala-autoposter && sudo bash deploy/vps-setup.sh
# the installer asks for ANTHROPIC_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_KEY
# (no editor), then sets up venv + chromium + timers. Threads tokens already
# live in Supabase, so they aren't needed here.
```

`deploy/vps-setup.sh` installs a venv + headless Chromium and enables four
systemd timers (templated `tala@.service` + `deploy/systemd/*.timer`):

| Timer | Job | Schedule (self-throttled) |
|---|---|---|
| `tala@post-tala` | tala posts | hourly → ~every 2h |
| `tala@post-blacksea` | blacksea posts | hourly 06-19 → ~3-4/day |
| `tala@comment-tala` | tala comments | every 30 min 06-19 |
| `tala@refresh` | scrape signals + comment targets | every 3h |

```bash
systemctl list-timers 'tala@*'        # see next fire times
journalctl -u 'tala@*' -f             # live logs
.venv/bin/python main.py --brand tala --publish   # post on demand
```

Notes: keep the VPS clock in **UTC** (the daytime windows assume it). Posting
needs no scraper; **commenting** needs a logged-in `parser/scout_session.json`
(run `python -m parser.scraper --login` on your Mac, then `scp` the file over).
Once the VPS is confirmed working, disable the Vercel project + GitHub workflows.

## Run on a VPS with systemd (auto-restart on reboot)

`/etc/systemd/system/tala-autoposter.service`:

```ini
[Unit]
Description=Tala Threads Autoposter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tala
WorkingDirectory=/home/tala/tala-autoposter
ExecStart=/home/tala/tala-autoposter/.venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/tala/tala-autoposter/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tala-autoposter
sudo systemctl status tala-autoposter
journalctl -u tala-autoposter -f      # live logs
```

`Restart=always` brings the scheduler back after crashes and reboots.

## Notes / deviations from the original spec

- **PublisherAgent** uses the real Postiz contract (endpoint, raw-key auth, `CreatePostDto`
  body with required `date`, list response → `postId`). The spec's example would 401/400.
- **MemoryAgent** adds `mark_published(row_id, postiz_id)` / `mark_failed(row_id)`: a draft
  is saved with `postiz_id=None`, so the documented `update_post_status(postiz_id, …)`
  alone can't locate it. `save_post` returns the row id to bridge this.
- **Cadence:** publishes every hour (`type:"now"`) as specified. Tune with
  `POST_INTERVAL_HOURS`.
