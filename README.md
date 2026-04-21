# AI Newsletter Generator

A production-ready, AI-powered newsletter generator focused on **AI, economy,
capitalism, and global power shifts**. Fetches live news from RSS/NewsAPI,
ranks for signal, and generates a structured brief via a pluggable LLM backend
(Anthropic, OpenAI, or an offline mock).

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

## Features

- **Two ingestion sources**: 9 built-in RSS feeds (TechCrunch, Wired, Ars
  Technica, FT, Economist, NYT, Hacker News, Reuters) + optional NewsAPI.
- **Signal processing**: URL + Jaccard-similarity dedupe, keyword-weighted
  scoring, source-quality boost, recency decay.
- **Swappable LLM**: Anthropic, OpenAI, or a deterministic `mock` backend that
  works fully offline.
- **Dual output**: Markdown (always) + self-contained HTML (optional).
- **Modular architecture** — each pipeline stage lives in its own module.
- **Graceful failures**: one dead RSS feed or a missing SDK never breaks the run.

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
python main.py -v               # verbose / debug logging
```

Output is written to `output/newsletter_<YYYY-MM-DD>.md` and (if
`EMIT_HTML=true`) `.html`. Ranked article metadata is cached to
`data/ranked_<YYYY-MM-DD>.json` for debugging/reuse.

---

## Project Structure

```
Ai-News-letter/
├── main.py                      # CLI entry point
├── config.py                    # env-driven settings
├── requirements.txt             # Python dependencies
├── .env.example                 # configuration template
├── data/                        # cached ranked articles (gitignored)
├── output/                      # generated newsletters (gitignored)
└── modules/
    ├── fetch_news.py            # NewsAPI + RSS ingestion
    ├── process_news.py          # dedupe + rank
    ├── generate_newsletter.py   # LLM generation (Anthropic / OpenAI / mock)
    └── formatter.py             # Markdown + HTML output
```

## How it Works

1. **Ingestion** (`modules/fetch_news.py`) — hits NewsAPI if `NEWSAPI_KEY` is
   set, then every configured RSS feed. Normalizes to a common schema.
2. **Processing** (`modules/process_news.py`) — URL dedupe + title Jaccard
   near-dupe filter, then scores each article:
   `topical keywords + source quality + length + recency`.
3. **Generation** (`modules/generate_newsletter.py`) — builds system + user
   prompts, dispatches to the selected backend. Falls back to `mock` if the
   configured provider's SDK/key is missing.
4. **Formatting** (`modules/formatter.py`) — wraps the LLM body with a dated
   header and an auto-generated sources appendix; writes `.md` and `.html`.

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
| `No articles fetched` | You're offline, or a firewall is blocking all 9 RSS feeds. Try `python main.py -v` to see per-feed errors. |
| `UnicodeEncodeError` on Windows | Run `chcp 65001` first, or use Windows Terminal / PowerShell 7. |
| LLM call hangs / fails | Set `LLM_PROVIDER=mock` in `.env` to confirm the rest of the pipeline works. |

## Requirements

- **Python 3.10+**
- `requests`, `python-dotenv` (required)
- `anthropic`, `openai` (optional — only needed for those providers)

## Security

All secrets live in `.env` (loaded by `python-dotenv` via `config.py`). The
`.env` file is gitignored — **never commit real keys**. `.env.example` is the
tracked template.

## License

MIT
