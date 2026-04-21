"""CLI entry point for the newsletter generator.

Usage:
    python main.py                # full pipeline, writes /output/newsletter_<date>.md
    python main.py --dry-run      # fetch + process, skip LLM call, print summary
    python main.py --limit 20     # cap processed articles
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import settings
from modules.fetch_news import fetch_all
from modules.formatter import write_outputs
from modules.generate_newsletter import generate_newsletter
from modules.process_news import process


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run(limit: int | None = None, dry_run: bool = False, verbose: bool = False) -> int:
    _configure_logging(verbose)
    log = logging.getLogger("newsletter_ai")

    log.info("Starting pipeline (provider=%s, dry_run=%s)", settings.llm_provider, dry_run)

    raw = fetch_all()
    if not raw:
        log.error("No articles fetched. Check your RSS feeds / NewsAPI key / network.")
        return 2

    ranked = process(raw)
    if limit:
        ranked = ranked[:limit]

    # Persist the ranked dataset for debugging / reuse.
    cache_path = settings.data_dir / f"ranked_{datetime.utcnow():%Y-%m-%d}.json"
    cache_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Cached ranked articles to %s", cache_path)

    if dry_run:
        print(f"\nDRY RUN — top {min(10, len(ranked))} articles:\n")
        for idx, art in enumerate(ranked[:10], start=1):
            print(f" {idx:>2}. [{art['score']:>4}] {art['title']}  ({art['source']})")
        return 0

    body = generate_newsletter(ranked)
    md_path, html_path = write_outputs(body, ranked)

    print(f"\nOK - Newsletter written: {md_path}")
    if html_path:
        print(f"OK - HTML version:       {html_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI-powered newsletter generator")
    parser.add_argument("--limit", type=int, default=None, help="Cap ranked articles before LLM")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM call; print ranked list")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)
    return run(limit=args.limit, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
