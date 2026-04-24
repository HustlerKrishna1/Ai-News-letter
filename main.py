"""CLI entry point for the newsletter generator.

Usage:
    python main.py                          # full pipeline -> output/newsletter_<date>.md
    python main.py --dry-run                # fetch + process, skip LLM, print top-N summary
    python main.py --limit 20               # cap processed articles before LLM
    python main.py --deliver email,slack    # deliver via one or more channels
    python main.py --serve                  # start the FastAPI dashboard
    python main.py --no-enrich              # skip full-text enrichment (faster/offline)
    python main.py --no-critique            # skip the self-critique judge stage

Delivery channels: email, slack, discord, telegram (comma-separated).
LLM provider: set LLM_PROVIDER=mock|anthropic|openai in .env.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Ensure UTF-8 stdout on Windows consoles (default cp1252 chokes on em-dashes).
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

from config import settings
from modules import archive
from modules.delivery import deliver, update_rss_feed
from modules.editorial import run_editorial
from modules.enrich import enrich_articles
from modules.fetch_news import fetch_all
from modules.formatter import write_outputs
from modules.logging_setup import configure as configure_logging
from modules.process_news import canonical_url, process


def _issue_url(issue_date: str) -> Optional[str]:
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}/issue/{issue_date}"


def run(limit: Optional[int] = None,
        dry_run: bool = False,
        verbose: bool = False,
        deliver_channels: Optional[List[str]] = None,
        email_to: Optional[List[str]] = None,
        enrich: bool = True,
        critique: bool = True) -> int:
    configure_logging(verbose=verbose)
    log = logging.getLogger("newsletter_ai")

    # Ensure archive is ready before the fetch so cross-run dedup works.
    archive.init()

    log.info("Starting pipeline (provider=%s, dry_run=%s, deliver=%s)",
             settings.llm_provider, dry_run, deliver_channels or [])

    # 1. Fetch from every configured source.
    raw = fetch_all()
    if not raw:
        log.error("No articles fetched. Check your sources / API keys / network.")
        return 2

    # 2. Record every observed article in the archive (for trending + dedup).
    try:
        archive.upsert_articles(raw, canonical_fn=canonical_url)
    except Exception as exc:  # noqa: BLE001 - archive must never break the run
        log.warning("archive.upsert_articles failed: %s", exc)

    # 3. Process: in-run dedup + cross-run dedup + rank + cap.
    ranked = process(raw)
    if limit:
        ranked = ranked[:limit]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    cache_path = settings.data_dir / f"ranked_{today}.json"
    cache_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Cached ranked articles to %s", cache_path)

    if dry_run:
        print(f"\nDRY RUN - top {min(10, len(ranked))} of {len(ranked)} ranked articles:\n")
        for idx, art in enumerate(ranked[:10], start=1):
            print(f" {idx:>2}. [{art['score']:>5}] {art['title']}  ({art['source']})")
        return 0

    # 4. Enrich top-N with full article text so sections cite real details.
    if enrich and settings.enrich_enabled:
        ranked = enrich_articles(ranked, top_n=settings.enrich_top_n)

    # 5. Run the multi-stage editorial pipeline.
    trending = archive.trending_topics(days=7, top_n=10)
    # Respect CLI critique override by temporarily toggling the setting.
    if not critique:
        object.__setattr__(settings, "critique_enabled", False)
    result = run_editorial(ranked, trending=trending)

    body = result["body"]
    subject = result["subject"]
    featured = result["featured"]

    # 6. Build Markdown + HTML and write to disk.
    meta = {
        "clusters": result.get("clusters"),
        "critique": result.get("critique"),
        "provider": result.get("provider"),
    }
    md_path, html_path = write_outputs(body, featured, subject=subject, meta=meta)

    print(f"\nOK - Newsletter written: {md_path}")
    if html_path:
        print(f"OK - HTML version:       {html_path}")
    if result.get("critique"):
        print(f"OK - Quality score:      {result['critique'].get('overall', '?'):.1f}/10")

    # 7. Persist issue metadata to the archive and mark featured URLs.
    try:
        archive.record_issue({
            "issue_date": today,
            "subject": subject,
            "markdown_path": str(md_path),
            "html_path": str(html_path) if html_path else None,
            "article_count": len(featured),
            "cluster_count": len(result.get("clusters") or []),
            "llm_provider": result.get("provider"),
            "llm_ms": result.get("llm_ms"),
            "quality_score": (result.get("critique") or {}).get("overall"),
            "critique": result.get("critique"),
        })
        archive.mark_featured(
            [canonical_url(a.get("url", "")) for a in featured],
            issue_date=today,
        )
        # Count cluster names so trending topics reflect real editorial weight.
        cluster_counts = {c["name"]: c["count"] for c in (result.get("clusters") or [])}
        if cluster_counts:
            archive.record_topic_counts(today, cluster_counts)
    except Exception as exc:  # noqa: BLE001
        log.warning("archive.record_issue failed: %s", exc)

    # 8. Refresh the RSS feed so subscribers see the new issue.
    try:
        update_rss_feed(archive.list_issues(limit=50))
    except Exception as exc:  # noqa: BLE001
        log.warning("RSS feed update failed: %s", exc)

    # 9. Deliver to any requested channels.
    channels = deliver_channels or settings.delivery_channels
    if channels:
        body_html = html_path.read_text(encoding="utf-8") if html_path else ""
        results = deliver(
            subject=subject,
            body_md=Path(md_path).read_text(encoding="utf-8"),
            body_html=body_html,
            issue_date=today,
            channels=channels,
            issue_url=_issue_url(today),
            email_recipients=email_to,
        )
        for channel, status in results.items():
            marker = "OK" if status == "ok" else "WARN"
            print(f"{marker} - {channel}: {status}")
        if any(s != "ok" for s in results.values()):
            return 3
    return 0


def serve(host: str, port: int) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        print(
            "uvicorn is required for --serve. Install with:\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    archive.init()  # so the dashboard can query stats even before the first run
    uvicorn.run("webui:app", host=host, port=port, reload=False, log_level="info")
    return 0


def _parse_channels(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI-powered newsletter generator (v3)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap ranked articles before the LLM")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip LLM call; print ranked list")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Debug logging")
    parser.add_argument("--deliver", type=str, default=None,
                        help="Comma-separated channels: email,slack,discord,telegram")
    parser.add_argument("--email-to", action="append", default=None,
                        help="Override recipient(s); repeatable")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip full-text enrichment (faster / offline)")
    parser.add_argument("--no-critique", action="store_true",
                        help="Skip the self-critique judge stage")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI dashboard instead of running the pipeline")
    parser.add_argument("--host", default=settings.webui_host, help="Web UI host")
    parser.add_argument("--port", type=int, default=settings.webui_port, help="Web UI port")

    # Back-compat shim: `--email` still works as `--deliver email`.
    parser.add_argument("--email", action="store_true",
                        help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.serve:
        return serve(args.host, args.port)

    channels = _parse_channels(args.deliver)
    if args.email and "email" not in channels:
        channels.append("email")

    return run(
        limit=args.limit,
        dry_run=args.dry_run,
        verbose=args.verbose,
        deliver_channels=channels or None,
        email_to=args.email_to,
        enrich=not args.no_enrich,
        critique=not args.no_critique,
    )


if __name__ == "__main__":
    sys.exit(main())
