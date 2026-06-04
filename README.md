# Tala Autonomous Threads Autoposter

A 4-agent Python pipeline that researches, writes, and publishes one Threads post for
**@tala.sav** every hour via a self-hosted [Postiz](https://github.com/gitroomhq/postiz-app)
instance. Runs unattended on an Ubuntu VPS.

```
MemoryAgent → ParserAgent → WriterAgent → MemoryAgent → PublisherAgent
(pick topic)   (research)     (write post)   (save draft)   (publish to Postiz)
```

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
python main.py            # start the hourly scheduler (fires once immediately, then every hour)
python main.py --test     # run once, print the post, DO NOT publish
python main.py --dry-run  # run pipeline, print the post, skip the Postiz call
python main.py --stats    # print the last 10 posts (topic + status) from memory.db
```

On first run `data/memory.db` is auto-created and `topic_rotation` is seeded from
`config/topics.json`. Logs rotate daily into `logs/autoposter.log.YYYY-MM-DD`.

> `--test` / `--dry-run` still pick a topic (bumps rotation) and write a `draft` row, so
> they touch `memory.db`. Delete `data/memory.db` to reset.

## Plugging in the real parser

`parser/scraper.py` is a **placeholder** returning mock signals so the pipeline runs out
of the box. Replace the file with Tala's real parser, keeping this exact signature:

```python
def fetch_posts(keywords: list[str]) -> list[dict]:
    # -> [{"text": str, "source": str, "url": str, "keyword": str}, ...]
```

Nothing else needs to change.

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
