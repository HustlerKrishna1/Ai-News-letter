"""FastAPI dashboard for the newsletter.

Endpoints:
  GET  /                       Jinja2 dashboard: stats, trending, past issues, search
  GET  /search?q=term          Archive search UI
  GET  /issue/{date}           rendered HTML for a past issue
  GET  /issue/{date}/markdown  raw markdown for a past issue
  GET  /issues.json            past issues as JSON (from archive)
  GET  /ranked/{date}          cached ranked articles for a run
  GET  /config                 current topic/source configuration
  GET  /rss.xml                RSS 2.0 feed
  GET  /health                 liveness probe (for container healthchecks)
  POST /generate               trigger a fresh pipeline run (background task)

Run:
    uvicorn webui:app --host 127.0.0.1 --port 8000
    # or
    python main.py --serve
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import settings
from modules import archive
from modules.delivery import update_rss_feed

log = logging.getLogger(__name__)

app = FastAPI(title="Newsletter AI", version="3.0")

_TEMPLATE_DIR = settings.project_root / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_run_lock = asyncio.Lock()


@app.on_event("startup")
async def _on_startup() -> None:
    archive.init()


def _render(template_name: str, **context) -> str:
    return _env.get_template(template_name).render(**context)


def _settings_view() -> Dict:
    return {
        "llm_provider": settings.llm_provider,
        "email_provider": settings.email_provider or None,
        "delivery_channels": ", ".join(settings.delivery_channels),
        "hn_enabled": settings.hn_enabled,
        "reddit_enabled": settings.reddit_enabled,
        "arxiv_enabled": settings.arxiv_enabled,
        "github_trending_enabled": settings.github_trending_enabled,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(q: Optional[str] = None) -> HTMLResponse:
    try:
        stats = archive.stats()
        trending = archive.trending_topics(days=7, top_n=10)
        issues = archive.list_issues(limit=100)
    except Exception as exc:  # noqa: BLE001
        log.warning("Archive query failed: %s", exc)
        stats = {"issues_count": 0, "articles_seen": 0,
                 "articles_featured": 0, "avg_quality": None}
        trending = []
        issues = _list_issues_from_disk()

    # Fallback: if the archive has no issues recorded yet but there are
    # Markdown files on disk, surface them so the dashboard isn't empty.
    if not issues:
        issues = _list_issues_from_disk()

    return HTMLResponse(_render(
        "dashboard.html.j2",
        cfg=_settings_view(),
        stats=stats,
        trending=trending,
        issues=issues,
        q=q,
    ))


@app.get("/search", response_class=HTMLResponse)
async def search(q: str = "") -> HTMLResponse:
    results = archive.search_articles(q, limit=100) if q.strip() else []
    return HTMLResponse(_render("search.html.j2", q=q, results=results))


def _list_issues_from_disk() -> List[Dict]:
    """Fallback when the archive has no rows yet: scan the output dir."""
    issues: List[Dict] = []
    for path in sorted(settings.output_dir.glob("newsletter_*.md"), reverse=True):
        try:
            date_str = path.stem.split("_", 1)[1]
        except IndexError:
            continue
        issues.append({
            "issue_date": date_str,
            "subject": None,
            "markdown_path": str(path),
            "html_path": str(path.with_suffix(".html")) if path.with_suffix(".html").exists() else None,
            "article_count": None,
            "cluster_count": None,
            "llm_provider": None,
            "quality_score": None,
        })
    return issues


@app.get("/issues.json")
async def issues_json() -> JSONResponse:
    issues = archive.list_issues(limit=200)
    if not issues:
        issues = _list_issues_from_disk()
    return JSONResponse(issues)


@app.get("/issue/{date}", response_class=HTMLResponse)
async def issue_html(date: str) -> HTMLResponse:
    html_path = settings.output_dir / f"newsletter_{date}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail=f"No HTML issue for {date}")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


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
        "delivery_channels": settings.delivery_channels,
        "rss_feeds_count": len(settings.rss_feeds),
        "hn_enabled": settings.hn_enabled,
        "reddit_enabled": settings.reddit_enabled,
        "arxiv_enabled": settings.arxiv_enabled,
        "github_trending_enabled": settings.github_trending_enabled,
        "enrich_enabled": settings.enrich_enabled,
        "critique_enabled": settings.critique_enabled,
        "cross_run_dedup": settings.cross_run_dedup,
        "max_total_articles": settings.max_total_articles,
    })


@app.get("/rss.xml")
async def rss_feed() -> Response:
    feed_path = settings.output_dir / "rss.xml"
    # Rebuild on the fly so new issues appear without waiting for the next run.
    try:
        issues = archive.list_issues(limit=50) or _list_issues_from_disk()
        update_rss_feed(issues, feed_path=feed_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not rebuild RSS: %s", exc)

    if not feed_path.exists():
        raise HTTPException(status_code=404, detail="RSS feed not generated yet")
    return Response(
        content=feed_path.read_bytes(),
        media_type="application/rss+xml",
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe. Returns 200 + a few basic numbers."""
    try:
        stats = archive.stats()
        ok = True
    except Exception:  # noqa: BLE001 - this endpoint must never throw
        stats = {}
        ok = False
    return JSONResponse({
        "ok": ok,
        "issues": stats.get("issues_count", 0),
        "articles": stats.get("articles_seen", 0),
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "version": app.version,
    })


@app.get("/ranked/{date}")
async def ranked_json(date: str) -> JSONResponse:
    path = settings.data_dir / f"ranked_{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No ranked data for {date}")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


def _run_sync() -> int:
    from main import run as run_pipeline  # lazy import to avoid cycles
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
