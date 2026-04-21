"""FastAPI dashboard for the newsletter.

Endpoints:
  GET  /                       dashboard listing past issues
  GET  /issue/{date}           rendered HTML for a past issue
  GET  /issue/{date}/markdown  raw markdown for a past issue
  GET  /config                 current topic/source configuration
  POST /generate               trigger a fresh pipeline run

Run:
    uvicorn webui:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from config import settings
from main import run as run_pipeline

log = logging.getLogger(__name__)

app = FastAPI(title="Newsletter AI", version="2.0")

_ISSUE_RE = re.compile(r"newsletter_(\d{4}-\d{2}-\d{2})\.md$")
_run_lock = asyncio.Lock()


def _list_issues() -> List[Dict]:
    issues: List[Dict] = []
    for path in sorted(settings.output_dir.glob("newsletter_*.md"), reverse=True):
        match = _ISSUE_RE.search(path.name)
        if not match:
            continue
        date_str = match.group(1)
        html = path.with_suffix(".html")
        issues.append({
            "date": date_str,
            "markdown": path.name,
            "html": html.name if html.exists() else None,
            "size_kb": round(path.stat().st_size / 1024, 1),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return issues


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    issues = _list_issues()
    rows = "\n".join(
        f"<tr><td>{i['date']}</td>"
        f"<td><a href='/issue/{i['date']}'>view</a></td>"
        f"<td><a href='/issue/{i['date']}/markdown'>md</a></td>"
        f"<td>{i['size_kb']} KB</td>"
        f"<td>{i['mtime']}</td></tr>"
        for i in issues
    ) or "<tr><td colspan=5><em>No issues yet. Run /generate.</em></td></tr>"

    email_status = settings.email_provider or "disabled"
    return f"""<!DOCTYPE html>
<html><head><meta charset=utf-8><title>Newsletter AI — Dashboard</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
h1{{border-bottom:2px solid #333;padding-bottom:.3rem}}
table{{border-collapse:collapse;width:100%;margin-top:1rem}}
th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #ddd}}
th{{background:#f5f5f5}}
.pill{{display:inline-block;padding:.1rem .5rem;border-radius:999px;background:#eef;color:#224;font-size:.8rem;margin-right:.3rem}}
form{{margin-top:1rem}}
button{{padding:.5rem 1rem;font-size:1rem;cursor:pointer}}
a{{color:#0366d6}}
.cfg{{margin-top:2rem;font-size:.9rem;color:#555}}
.cfg code{{background:#f0f0f0;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>Newsletter AI Dashboard</h1>
<p>
  <span class=pill>LLM: {settings.llm_provider}</span>
  <span class=pill>email: {email_status}</span>
  <span class=pill>HN: {"on" if settings.hn_enabled else "off"}</span>
  <span class=pill>Reddit: {"on" if settings.reddit_enabled else "off"}</span>
</p>
<form method=post action=/generate onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Running…';">
  <button type=submit>Generate new issue now</button>
</form>
<h2>Past issues</h2>
<table>
<thead><tr><th>Date</th><th>HTML</th><th>Markdown</th><th>Size</th><th>Modified</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class=cfg>
<p><a href=/config>/config</a> · <a href=/issues.json>/issues.json</a></p>
</div>
</body></html>
"""


@app.get("/issues.json")
async def issues_json() -> JSONResponse:
    return JSONResponse(_list_issues())


@app.get("/issue/{date}", response_class=HTMLResponse)
async def issue_html(date: str) -> str:
    html_path = settings.output_dir / f"newsletter_{date}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail=f"No HTML issue for {date}")
    return html_path.read_text(encoding="utf-8")


@app.get("/issue/{date}/markdown", response_class=PlainTextResponse)
async def issue_markdown(date: str) -> str:
    md_path = settings.output_dir / f"newsletter_{date}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"No markdown issue for {date}")
    return md_path.read_text(encoding="utf-8")


@app.get("/config")
async def config_view() -> JSONResponse:
    return JSONResponse({
        "llm_provider": settings.llm_provider,
        "email_provider": settings.email_provider or None,
        "email_to": settings.email_to,
        "rss_feeds": settings.rss_feeds,
        "hn_enabled": settings.hn_enabled,
        "reddit_enabled": settings.reddit_enabled,
        "reddit_subs": settings.reddit_subs,
        "max_total_articles": settings.max_total_articles,
    })


def _run_sync() -> int:
    try:
        return run_pipeline(dry_run=False, verbose=False)
    except Exception:
        log.exception("Pipeline run failed")
        return 1


@app.post("/generate")
async def generate(background: BackgroundTasks) -> JSONResponse:
    if _run_lock.locked():
        return JSONResponse(
            {"ok": False, "error": "a run is already in progress"},
            status_code=409,
        )

    async def _locked_run() -> None:
        async with _run_lock:
            await asyncio.to_thread(_run_sync)

    background.add_task(_locked_run)
    return JSONResponse({"ok": True, "message": "pipeline started in background"})


@app.get("/ranked/{date}")
async def ranked_json(date: str) -> JSONResponse:
    path = settings.data_dir / f"ranked_{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No ranked data for {date}")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
