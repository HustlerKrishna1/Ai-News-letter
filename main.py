"""CLI entry point for the newsletter generator.

Usage:
    python main.py                # full pipeline, writes /output/newsletter_<date>.md
    python main.py --dry-run      # fetch + process, skip LLM call, print summary
    python main.py --limit 20     # cap processed articles
    python main.py --email        # also deliver the issue via configured provider
    python main.py --serve        # start the FastAPI dashboard instead
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 stdout on Windows consoles (default cp1252 chokes on em-dashes).
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

from config import settings
from modules.fetch_news import fetch_all
from modules.formatter import markdown_to_html, write_outputs
from modules.generate_newsletter import generate_newsletter
from modules.process_news import process


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run(limit: int | None = None, dry_run: bool = False, verbose: bool = False,
        email: bool = False, email_to: list[str] | None = None) -> int:
    _configure_logging(verbose)
    log = logging.getLogger("newsletter_ai")

    log.info("Starting pipeline (provider=%s, dry_run=%s, email=%s)",
             settings.llm_provider, dry_run, email)

    raw = fetch_all()
    if not raw:
        log.error("No articles fetched. Check your sources / API keys / network.")
        return 2

    ranked = process(raw)
    if limit:
        ranked = ranked[:limit]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    cache_path = settings.data_dir / f"ranked_{today}.json"
    cache_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Cached ranked articles to %s", cache_path)

    if dry_run:
        print(f"\nDRY RUN - top {min(10, len(ranked))} articles:\n")
        for idx, art in enumerate(ranked[:10], start=1):
            print(f" {idx:>2}. [{art['score']:>4}] {art['title']}  ({art['source']})")
        return 0

    body = generate_newsletter(ranked)
    md_path, html_path = write_outputs(body, ranked)

    print(f"\nOK - Newsletter written: {md_path}")
    if html_path:
        print(f"OK - HTML version:       {html_path}")

    if email:
        from modules.email_sender import EmailError, send_newsletter
        md_text = Path(md_path).read_text(encoding="utf-8")
        html_text = (
            Path(html_path).read_text(encoding="utf-8")
            if html_path else markdown_to_html(md_text)
        )
        try:
            send_newsletter(md_text, html_text, today, recipients=email_to)
            print("OK - Email delivered.")
        except EmailError as exc:
            log.error("Email delivery failed: %s", exc)
            print(f"WARN - Email delivery failed: {exc}", file=sys.stderr)
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
    uvicorn.run("webui:app", host=host, port=port, reload=False, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI-powered newsletter generator")
    parser.add_argument("--limit", type=int, default=None, help="Cap ranked articles before LLM")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM call; print ranked list")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--email", action="store_true",
                        help="After generating, deliver via EMAIL_PROVIDER")
    parser.add_argument("--email-to", action="append", default=None,
                        help="Override recipient(s); repeatable")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI dashboard instead of running the pipeline")
    parser.add_argument("--host", default=settings.webui_host, help="Web UI host")
    parser.add_argument("--port", type=int, default=settings.webui_port, help="Web UI port")
    args = parser.parse_args(argv)

    if args.serve:
        return serve(args.host, args.port)

    return run(
        limit=args.limit,
        dry_run=args.dry_run,
        verbose=args.verbose,
        email=args.email,
        email_to=args.email_to,
    )


if __name__ == "__main__":
    sys.exit(main())
