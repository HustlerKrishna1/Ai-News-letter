# AI Newsletter Generator

A production-ready, AI-powered newsletter generator focused on **AI, economy,
capitalism, and global power shifts**. Fetches live news from RSS, NewsAPI,
Hacker News, and Reddit; deduplicates across sources; ranks for signal; and
generates a structured brief via a pluggable LLM backend (Anthropic, OpenAI, or
an offline mock).

**Runs with zero API keys** by default — `LLM_PROVIDER=mock` produces a real,
structured newsletter so you can verify the entire pipeline before wiring up
paid APIs.

---

## Quick Start (60 seconds, no API keys required)

```bash
# 1. Clone the repo
git clone https://github.com/HustlerKrishna1/Ai-News-letter.git
cd Ai-News-letter

# 2. Create a virtualenv and install deps
python -m venv .venv

# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

pip install -r requirements.txt

# 3. Copy the environment template
cp .env.example .env            # macOS / Linux
copy .env.example .env          # Windows

# 4. Run it
python main.py
```

You should see output like:

```
OK - Newsletter written: output/newsletter_2026-04-21.md
OK - HTML version:       output/newsletter_2026-04-21.html
```

Open the generated `.md` or `.html` file in `output/` to see your newsletter.

---

## What's in v2

- **Four ingestion sources**: RSS feeds, NewsAPI, Hacker News (Firebase API),
  Reddit (public JSON). HN and Reddit are **on by default** and need no keys.
- **Cross-source deduplication**: canonical URL normalization strips tracking
  params and collapses duplicate stories across sources; the highest-quality
  source wins.
- **Email delivery**: ship the issue via SMTP (Gmail, Fastmail, self-hosted) or
  SendGrid with a single `--email` flag.
- **Web UI dashboard**: FastAPI app at `http://127.0.0.1:8000` listing past
  issues, viewing generated HTML, inspecting config, and triggering fresh runs.
- **Scheduling**: one-shot installers for Windows Task Scheduler
  (`scripts/schedule_windows.ps1`) and cron (`scripts/schedule_cron.sh`).

---

## Features

- **Four ingestion sources**: 8 built-in RSS feeds (TechCrunch, Wired, Ars
  Technica, FT, Economist, NYT, Reuters), Hacker News top stories, 8
  subreddits, plus optional NewsAPI.
- **Signal processing**: canonical URL + Jaccard-similarity dedupe,
  keyword-weighted scoring, source-quality boost, recency decay.
- **Swappable LLM**: Anthropic, OpenAI, or a deterministic `mock` backend that
  works fully offline.
- **Dual output**: Markdown (always) + self-contained HTML (optional).
- **Email delivery**: SMTP or SendGrid, HTML + plain-text multipart.
- **Web dashboard**: FastAPI UI for browsing, inspecting, and triggering runs.
- **Modular architecture** — each pipeline stage lives in its own module.
- **Graceful failures**: one dead feed or missing SDK never breaks the run.

---

## Using a Real LLM (optional)

Edit `.env` and set **either**:

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
```

Then run `python main.py` again. If the SDK or key is missing, the generator
automatically falls back to `mock` so your run never fails blind.

Add a NewsAPI key for richer ingestion (optional — grab a free key at
[newsapi.org](https://newsapi.org)):

```bash
NEWSAPI_KEY=your_key_here
```

---

## CLI Usage

```bash
python main.py                  # full pipeline
python main.py --dry-run        # fetch + rank only, print top 10 (no LLM call)
python main.py --limit 20       # cap articles before the LLM call
python main.py --email          # also deliver via EMAIL_PROVIDER (SMTP/SendGrid)
python main.py --email --email-to you@example.com  # override recipient
python main.py --serve          # start the FastAPI dashboard on :8000
python main.py -v               # verbose / debug logging
```

Output is written to `output/newsletter_<YYYY-MM-DD>.md` and (if
`EMIT_HTML=true`) `.html`. Ranked article metadata is cached to
`data/ranked_<YYYY-MM-DD>.json` for debugging/reuse.

---

## Email Delivery

Pick a provider in `.env`:

```bash
EMAIL_PROVIDER=smtp             # or: sendgrid
EMAIL_FROM=you@example.com
EMAIL_TO=alice@example.com,bob@example.com
EMAIL_SUBJECT_PREFIX=Signal Brief

# SMTP (e.g., Gmail with an app password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASSWORD=your-app-password
SMTP_USE_TLS=true

# — or —

# SendGrid
SENDGRID_API_KEY=SG.xxxx
```

Then `python main.py --email` attaches both plain-text and HTML parts.

---

## Web Dashboard

```bash
python main.py --serve          # or: uvicorn webui:app --port 8000
```

Visit `http://127.0.0.1:8000` to:

- Browse past issues with size + modified timestamps
- View a rendered issue (`/issue/<YYYY-MM-DD>`) or the raw markdown
- Inspect live config (`/config`) and the ranked data (`/ranked/<YYYY-MM-DD>`)
- Trigger a fresh pipeline run from the UI (`POST /generate`)

The `/generate` endpoint uses a lock so concurrent triggers don't pile up.

---

## Scheduling

**Windows (Task Scheduler):**

```powershell
# from project root, in PowerShell
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

Cron output goes to `output/cron.log` for troubleshooting.

---

## Project Structure

```
Ai-News-letter/
├── main.py                      # CLI entry point (+ --serve, --email)
├── webui.py                     # FastAPI dashboard
├── config.py                    # env-driven settings
├── requirements.txt             # Python dependencies
├── .env.example                 # configuration template
├── data/                        # cached ranked articles (gitignored)
├── output/                      # generated newsletters (gitignored)
├── scripts/
│   ├── schedule_windows.ps1     # Windows Task Scheduler installer
│   └── schedule_cron.sh         # cron installer
└── modules/
    ├── fetch_news.py            # RSS + NewsAPI + HN + Reddit ingestion
    ├── process_news.py          # canonical-URL dedupe + rank
    ├── generate_newsletter.py   # LLM generation (Anthropic / OpenAI / mock)
    ├── email_sender.py          # SMTP + SendGrid delivery
    └── formatter.py             # Markdown + HTML output
```

## How it Works

1. **Ingestion** (`modules/fetch_news.py`) — hits NewsAPI (if key set), RSS
   feeds, Hacker News top stories above `HN_MIN_SCORE`, and each configured
   subreddit's top-of-day. Normalizes to a common schema.
2. **Processing** (`modules/process_news.py`) — canonical-URL dedupe (strips
   `utm_*`/`gclid`/etc.) + title Jaccard near-dupe filter, preferring the
   highest-quality source when the same story surfaces twice. Then scores:
   `topical keywords + source quality + length + recency`.
3. **Generation** (`modules/generate_newsletter.py`) — builds system + user
   prompts, dispatches to the selected backend. Falls back to `mock` if the
   configured provider's SDK/key is missing.
4. **Formatting** (`modules/formatter.py`) — wraps the LLM body with a dated
   header and an auto-generated sources appendix; writes `.md` and `.html`.
5. **Delivery** (`modules/email_sender.py`, optional) — multipart email with
   plain-text + HTML bodies via SMTP or SendGrid.

## Extending

- **Add an ingestion source**: write `fetch_<name>() -> List[Dict]` in
  `modules/fetch_news.py` and concatenate inside `fetch_all()`.
  Each article needs `title`, `summary`, `source`, `url`, `published_at`.
- **Add a new LLM backend**: implement a class with `generate(system, user)`
  and register it in `_pick_client()` in `modules/generate_newsletter.py`.
- **Tune ranking**: edit `KEYWORD_WEIGHTS` / `SOURCE_QUALITY` in
  `modules/process_news.py`, or replace `score_article()` entirely.
- **Change the newsletter structure**: edit `SYSTEM_PROMPT` in
  `modules/generate_newsletter.py`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'requests'` | Virtualenv isn't activated. Re-run the activate step. |
| `ModuleNotFoundError: fastapi` on `--serve` | Run `pip install -r requirements.txt` — v2 added FastAPI/uvicorn. |
| `No articles fetched` | You're offline, or a firewall is blocking every source. Try `python main.py -v` to see per-source errors. |
| `UnicodeEncodeError` on Windows | Run `chcp 65001` first, or use Windows Terminal / PowerShell 7. |
| LLM call hangs / fails | Set `LLM_PROVIDER=mock` in `.env` to confirm the rest of the pipeline works. |
| `EMAIL_PROVIDER is not set` | Edit `.env` and set `EMAIL_PROVIDER=smtp` or `sendgrid`, plus the matching credentials. |
| Reddit 429 / blocked | Reddit occasionally rate-limits raw IPs; set `REDDIT_ENABLED=false` or run less often. |

## Requirements

- **Python 3.10+**
- `requests`, `python-dotenv` (required)
- `fastapi`, `uvicorn` (required for `--serve`)
- `anthropic`, `openai` (optional — only needed for those providers)

## Security

All secrets live in `.env` (loaded by `python-dotenv` via `config.py`). The
`.env` file is gitignored — **never commit real keys**. `.env.example` is the
tracked template.

The web dashboard binds to `127.0.0.1` by default and has **no authentication**
— do not expose it directly to the internet. If you need remote access, put it
behind an authenticated reverse proxy or SSH-tunnel to it.

## License

MIT
