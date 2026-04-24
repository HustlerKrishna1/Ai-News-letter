# AI Newsletter Generator (v3)

A **production-grade**, agent-style AI newsletter generator focused on **AI,
economy, capitalism, and global power shifts**. Ingests six source types,
deduplicates across runs, clusters by theme, writes sections in parallel with
an LLM, critiques its own draft, and delivers to file / email / Slack /
Discord / Telegram / RSS.

**Runs with zero API keys** — `LLM_PROVIDER=mock` produces a fully-structured
newsletter end-to-end so you can validate the entire pipeline before wiring up
paid APIs.

---

## What's new in v3

- **Multi-stage editorial pipeline** (`modules/editorial.py`) —
  triage → cluster → per-cluster section (parallel) → editor → subject line →
  self-critique judge (with regenerate-if-below-threshold).
- **Topic clustering** (`modules/cluster.py`) — TF-IDF + cosine similarity,
  pure-Python / stdlib, no numpy or scikit-learn. Auto-labels clusters as
  "AI Infrastructure", "Markets & Economy", "Geopolitics", etc.
- **Full-text enrichment** (`modules/enrich.py`) — stdlib-only HTML
  readability extractor fetches the top-N article bodies so sections cite
  real details instead of just summaries. Parallelized.
- **SQLite archive** (`modules/archive.py`) — cross-run memory: skips
  articles already featured in the last 14 days, tracks trending topics,
  persists every issue's quality score + LLM provider + timing.
- **Two new sources** (`modules/sources_extra.py`) — arXiv (cs.AI / cs.LG /
  cs.CL) and GitHub Trending, on top of the v2 RSS + NewsAPI + HN + Reddit.
- **Retry with backoff** (`modules/retry.py`) — exponential backoff + jitter
  for 5xx / 429 / timeouts / connection resets; 4xx fails fast.
- **Multi-channel delivery** (`modules/delivery.py`) — one flag sends to any
  of email, Slack, Discord, Telegram. Independent errors per channel.
- **RSS 2.0 feed** — `output/rss.xml` + `/rss.xml` endpoint, regenerated on
  every run and on demand.
- **Jinja2 templates** — email / dashboard / search all moved to
  `templates/*.html.j2` with autoescape. No more HTML-in-Python strings.
- **Structured JSON logs** (`LOG_FORMAT=json`) — one JSON object per line,
  ready for Datadog / Loki / ELK / Grafana.
- **Quality telemetry** — every issue stores a faithfulness / clarity /
  specificity / restraint score in the archive, surfaced in the dashboard.
- **Docker + docker-compose** — non-root container (`uid 10001`), healthcheck,
  one-shot `newsletter-job` profile, builds on `python:3.12-slim` + tini.
- **CI/CD** — GitHub Actions matrix (Python 3.11 + 3.12) with pytest and
  docker-build jobs, plus a scheduled daily workflow that runs the pipeline.
- **Test suite** — pytest covers process/cluster/archive/editorial/retry/enrich
  with a `tmp_path`-isolated filesystem fixture.

v2 features (multi-source, email, web UI, scheduling) are all still here and
fully integrated with the v3 stack.

---

## Quick Start (60 seconds, no API keys)

```bash
git clone https://github.com/HustlerKrishna1/Ai-News-letter.git
cd Ai-News-letter

python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env            # macOS / Linux
copy .env.example .env          # Windows

python main.py
```

Output:

```
OK - Newsletter written: output/newsletter_2026-04-23.md
OK - HTML version:       output/newsletter_2026-04-23.html
OK - Quality score:      7.5/10
```

Then start the dashboard:

```bash
python main.py --serve
# or: uvicorn webui:app --port 8000
```

Visit `http://127.0.0.1:8000` for the dashboard, search, issue history,
stats, trending topics, and `/rss.xml`.

---

## CLI

```bash
python main.py                              # full pipeline -> file output
python main.py --dry-run                    # fetch + rank only, print top 10
python main.py --limit 20                   # cap processed articles
python main.py --deliver email              # email + file
python main.py --deliver slack,telegram     # multi-channel
python main.py --email-to you@example.com   # override recipient(s)
python main.py --no-enrich                  # skip full-text fetch (faster)
python main.py --no-critique                # skip LLM-as-judge stage
python main.py --serve                      # start the dashboard
python main.py -v                           # verbose / debug logging
```

Cached ranked articles → `data/ranked_<YYYY-MM-DD>.json`.
Newsletters → `output/newsletter_<YYYY-MM-DD>.{md,html}`.
Archive DB → `data/archive.sqlite3` (WAL mode, safe for concurrent reads).

---

## LLM providers

Edit `.env` and set **one**:

```bash
# Anthropic (Claude)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-7

# — or —

# OpenAI (GPT)
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# — or (default) —

LLM_PROVIDER=mock
```

The mock provider produces a real, structured newsletter with stage-appropriate
content for every pipeline stage (triage, sections, editor, subject, critique).
Useful for CI, offline dev, and smoke tests.

If the configured SDK or key is missing, the pipeline automatically falls back
to `mock` so your run never hangs.

---

## Data sources

All six can be toggled in `.env`. Defaults are sensible — no keys required.

| Source | Key | Default |
| --- | --- | --- |
| RSS (8 built-in feeds) | — | on |
| NewsAPI | `NEWSAPI_KEY` | off if blank |
| Hacker News | `HN_ENABLED` | on (score ≥ 50) |
| Reddit | `REDDIT_ENABLED` | on (score ≥ 100, 8 subs) |
| arXiv | `ARXIV_ENABLED` | on (cs.AI / cs.LG / cs.CL) |
| GitHub Trending | `GITHUB_TRENDING_ENABLED` | on (all + python + ts) |

Failures in one source never break the others — per-source try/except wraps
every fetcher.

---

## Editorial pipeline

```
   fetch_all
       │
       ▼
 process (dedup + cross-run dedup + rank)
       │
       ▼
 enrich_articles (full-text for top-N)
       │
       ▼
 run_editorial
   ├─ stage_triage     (LLM picks ~15 of N candidates)
   ├─ cluster_articles (TF-IDF + cosine)
   ├─ stage_section    × N clusters (parallel ThreadPool)
   ├─ stage_editor     (assembles final body)
   ├─ stage_subject    (≤ 70-char email subject)
   └─ stage_critique   (0-10 scores; regenerate if < threshold)
       │
       ▼
 write_outputs (Markdown + Jinja2 HTML)
       │
       ▼
 archive.record_issue  +  update_rss_feed  +  deliver(channels)
```

Each stage flows through the same `LLMClient` interface, so Anthropic /
OpenAI / mock work identically. The mock client routes by `[stage:*]` marker
in the system prompt and returns stage-appropriate output for offline runs.

---

## Delivery channels

```bash
python main.py --deliver email,slack,discord,telegram
```

Each channel is independent; one failure does not block the others. Required
env keys:

- **email** — `EMAIL_PROVIDER=smtp|sendgrid` + credentials.
- **slack** — `SLACK_WEBHOOK_URL` (Incoming Webhook).
- **discord** — `DISCORD_WEBHOOK_URL` (Server → Integrations → Webhooks).
- **telegram** — `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

Set `DELIVERY_CHANNELS=email,slack` in `.env` to make those the default when
`--deliver` is not passed.

---

## Docker

```bash
# One-shot newsletter (runs, delivers, exits):
docker compose --profile job run --rm newsletter-job

# Long-running dashboard on :8000 with healthcheck:
docker compose up -d newsletter-web
```

The image is based on `python:3.12-slim`, runs under a non-root `app` user
(`uid 10001`), and uses `tini` as PID 1 for clean signal handling. Data and
output volumes are persisted in `./data` and `./output`.

---

## CI / CD

Two workflows ship in `.github/workflows/`:

- **ci.yml** — runs pytest on Python 3.11 + 3.12, plus a smoke-test import
  of the editorial pipeline, plus a docker build. Triggers on push / PR.
- **daily.yml** — scheduled `0 7 * * *` (07:00 UTC). Runs the pipeline with
  the provider secrets configured in your repo settings and uploads the
  generated issue as a workflow artifact (30-day retention).

Set these as GitHub **secrets** (encrypted): `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `NEWSAPI_KEY`, `SMTP_USER`, `SMTP_PASSWORD`,
`SENDGRID_API_KEY`, `SLACK_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL`,
`TELEGRAM_BOT_TOKEN`.

Set these as repo **variables** (plaintext): `LLM_PROVIDER`, `EMAIL_PROVIDER`,
`EMAIL_FROM`, `EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `TELEGRAM_CHAT_ID`,
`DELIVERY_CHANNELS`.

---

## Scheduling (local, no GitHub)

**Windows (Task Scheduler):**
```powershell
.\scripts\schedule_windows.ps1                  # daily 07:00 local
.\scripts\schedule_windows.ps1 -Time 09:30      # custom time
.\scripts\schedule_windows.ps1 -WithEmail       # pass --email
.\scripts\schedule_windows.ps1 -Remove          # uninstall
```

**Linux / macOS (cron):**
```bash
chmod +x scripts/schedule_cron.sh
./scripts/schedule_cron.sh install              # daily at 07:00
./scripts/schedule_cron.sh install 09 30        # custom HH MM
./scripts/schedule_cron.sh install-email        # with --email
./scripts/schedule_cron.sh remove
```

Cron output goes to `output/cron.log`.

---

## Tests

```bash
pip install -r requirements.txt
pytest -v --cov=modules --cov-report=term
```

The `isolate_fs` fixture in `tests/conftest.py` redirects every test's
`data/` and `output/` to `tmp_path`, so tests never touch your real archive
or generated files. `LLM_PROVIDER=mock` is forced for every test run.

---

## Web dashboard

`python main.py --serve` exposes:

| Endpoint | Description |
| --- | --- |
| `GET  /` | Dashboard: stats cards, trending pills, issues table, search box |
| `GET  /search?q=term` | Search past articles by title / summary |
| `GET  /issue/{date}` | Rendered HTML for a past issue |
| `GET  /issue/{date}/markdown` | Raw markdown for a past issue |
| `GET  /issues.json` | Issue metadata as JSON |
| `GET  /ranked/{date}` | Cached ranked articles for that date |
| `GET  /config` | Live config (non-secret) |
| `GET  /rss.xml` | RSS 2.0 feed of recent issues |
| `GET  /health` | Liveness probe (200 + stats) |
| `POST /generate` | Trigger a pipeline run (background task, locked) |

Bind to `127.0.0.1` by default — there's **no auth** built in. Put it behind
an authenticated reverse proxy (Cloudflare Access, Tailscale, etc.) if you
want remote access.

---

## Project structure

```
Ai-News-letter/
├── main.py                      # CLI entry point
├── webui.py                     # FastAPI dashboard
├── config.py                    # env-driven settings
├── requirements.txt
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .github/workflows/
│   ├── ci.yml                   # pytest + docker-build
│   └── daily.yml                # 07:00 UTC scheduled run
├── data/                        # cached articles + archive.sqlite3 (gitignored)
├── output/                      # generated newsletters + rss.xml (gitignored)
├── scripts/
│   ├── schedule_windows.ps1
│   └── schedule_cron.sh
├── templates/
│   ├── email.html.j2            # newsletter HTML (used by email + /issue)
│   ├── dashboard.html.j2
│   └── search.html.j2
├── tests/                       # pytest suite (isolated fs + mock LLM)
└── modules/
    ├── fetch_news.py            # RSS + NewsAPI + HN + Reddit
    ├── sources_extra.py         # arXiv + GitHub Trending
    ├── process_news.py          # dedup + cross-run dedup + rank
    ├── enrich.py                # full-text readability extraction
    ├── cluster.py               # TF-IDF topic clustering
    ├── editorial.py             # multi-stage LLM pipeline
    ├── generate_newsletter.py   # LLM clients (Anthropic / OpenAI / mock)
    ├── archive.py               # SQLite: articles, issues, trending
    ├── delivery.py              # Slack / Discord / Telegram / RSS router
    ├── email_sender.py          # SMTP + SendGrid
    ├── formatter.py             # Markdown + Jinja2 HTML
    ├── retry.py                 # exponential-backoff decorator
    └── logging_setup.py         # text + JSON structured logging
```

---

## Extending

- **New ingestion source**: write `fetch_<name>() -> List[Dict]` in
  `sources_extra.py` (or `fetch_news.py`) and append it to the tuple in
  `fetch_all()`. Each article needs `title`, `summary`, `source`, `url`,
  `published_at`. Wrap the HTTP call with `@with_retry`.
- **New delivery channel**: add a `send_<name>()` function in
  `modules/delivery.py` and wire it into `deliver()`'s channel switch.
- **New LLM backend**: implement a class with `generate(system, user) -> str`
  and register it in `_pick_client()` in `modules/editorial.py`
  (and `modules/generate_newsletter.py` for the legacy path).
- **Change cluster labels**: edit `_THEME_LABELS` in `modules/cluster.py`.
- **Tune editorial prompts**: each stage has its own `*_SYSTEM` constant
  at the top of `modules/editorial.py`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError` on any module | `pip install -r requirements.txt` |
| `No articles fetched` | Offline or firewall; try `python main.py -v` |
| `UnicodeEncodeError` on Windows | `chcp 65001`, or use Windows Terminal |
| LLM call hangs | Set `LLM_PROVIDER=mock` to isolate to ingestion |
| Reddit 429 | Backoff is automatic; or set `REDDIT_ENABLED=false` |
| Archive errors | Delete `data/archive.sqlite3*` to reset |
| Quality score always low | Your LLM provider may be slower / smaller — try a larger model |

---

## Security

- Secrets live in `.env` (loaded via `python-dotenv` in `config.py`); `.env`
  is gitignored. Never commit real keys.
- The web UI has no authentication — bind to `127.0.0.1` or put it behind an
  authenticated proxy.
- The Docker image runs as `uid 10001` and does not expose a shell by default.
- Telegram message bodies are MarkdownV2-escaped; the Jinja2 environment has
  autoescape enabled for all `html/xml` templates.

---

## Requirements

- **Python 3.10+** (tested on 3.11 and 3.12 in CI, developed on 3.14).
- `requests`, `python-dotenv`, `jinja2` (required).
- `fastapi`, `uvicorn` (required for `--serve`).
- `anthropic`, `openai` (optional — only for those providers).

## License

MIT
