"""SQLite-backed archive for articles, issues, and quality metrics.

Provides cross-run memory so the pipeline can:
  * Skip articles already featured in a past issue (cross-run dedup).
  * Compute trending topics from historical counts.
  * Serve a searchable archive of past issues from the web UI.
  * Track LLM latency, token estimates, and quality scores over time.

Schema is intentionally flat (no ORM) so it stays legible and migratable
via plain SQL. Opens a fresh connection per call so it is safe to share
across threads (FastAPI background tasks + CLI).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from config import settings

log = logging.getLogger(__name__)

DB_PATH: Path = settings.data_dir / "archive.sqlite3"


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    canonical_url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    url TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    featured_in TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_first_seen ON articles(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_articles_featured ON articles(featured_in);

CREATE TABLE IF NOT EXISTS issues (
    issue_date TEXT PRIMARY KEY,
    subject TEXT,
    markdown_path TEXT,
    html_path TEXT,
    article_count INTEGER,
    cluster_count INTEGER,
    llm_provider TEXT,
    llm_ms INTEGER,
    quality_score REAL,
    critique_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_mentions (
    issue_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    PRIMARY KEY (issue_date, topic)
);

CREATE INDEX IF NOT EXISTS idx_topic_mentions_topic ON topic_mentions(topic);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        yield conn
    finally:
        conn.close()


def init() -> None:
    """Create tables if they don't exist. Idempotent."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
    log.debug("Archive initialized at %s", DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_articles(articles: Iterable[Dict[str, Any]], canonical_fn) -> None:
    """Record observation of each article. Bumps seen_count on repeat."""
    now = _now()
    with _connect() as conn:
        for art in articles:
            canon = canonical_fn(art.get("url", ""))
            if not canon:
                continue
            conn.execute(
                """
                INSERT INTO articles (canonical_url, title, summary, source, url,
                                      published_at, first_seen_at, last_seen_at, seen_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    seen_count = articles.seen_count + 1
                """,
                (
                    canon,
                    art.get("title", "")[:500],
                    (art.get("summary") or "")[:2000],
                    art.get("source", "")[:200],
                    art.get("url", "")[:1000],
                    art.get("published_at", ""),
                    now,
                    now,
                ),
            )


def already_featured(canonical_urls: Iterable[str], within_days: int = 14) -> set[str]:
    """Return the subset of URLs already featured in an issue within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    urls = [u for u in canonical_urls if u]
    if not urls:
        return set()
    placeholders = ",".join("?" * len(urls))
    query = f"""
        SELECT canonical_url FROM articles
        WHERE canonical_url IN ({placeholders})
          AND featured_in IS NOT NULL
          AND featured_in >= ?
    """
    with _connect() as conn:
        rows = conn.execute(query, (*urls, cutoff[:10])).fetchall()
    return {row["canonical_url"] for row in rows}


def mark_featured(canonical_urls: Iterable[str], issue_date: str) -> None:
    urls = [u for u in canonical_urls if u]
    if not urls:
        return
    with _connect() as conn:
        for canon in urls:
            conn.execute(
                "UPDATE articles SET featured_in = ? WHERE canonical_url = ?",
                (issue_date, canon),
            )


def record_issue(issue: Dict[str, Any]) -> None:
    """Persist issue metadata (called after generation + delivery)."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO issues (issue_date, subject, markdown_path, html_path,
                                article_count, cluster_count, llm_provider,
                                llm_ms, quality_score, critique_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_date) DO UPDATE SET
                subject = excluded.subject,
                markdown_path = excluded.markdown_path,
                html_path = excluded.html_path,
                article_count = excluded.article_count,
                cluster_count = excluded.cluster_count,
                llm_provider = excluded.llm_provider,
                llm_ms = excluded.llm_ms,
                quality_score = excluded.quality_score,
                critique_json = excluded.critique_json
            """,
            (
                issue["issue_date"],
                issue.get("subject"),
                issue.get("markdown_path"),
                issue.get("html_path"),
                issue.get("article_count"),
                issue.get("cluster_count"),
                issue.get("llm_provider"),
                issue.get("llm_ms"),
                issue.get("quality_score"),
                json.dumps(issue.get("critique")) if issue.get("critique") else None,
                now,
            ),
        )


def record_topic_counts(issue_date: str, counts: Dict[str, int]) -> None:
    with _connect() as conn:
        for topic, count in counts.items():
            conn.execute(
                """
                INSERT INTO topic_mentions (issue_date, topic, mention_count)
                VALUES (?, ?, ?)
                ON CONFLICT(issue_date, topic) DO UPDATE SET
                    mention_count = excluded.mention_count
                """,
                (issue_date, topic, int(count)),
            )


def list_issues(limit: int = 100) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM issues ORDER BY issue_date DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_issue(issue_date: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_date = ?", (issue_date,)
        ).fetchone()
    return dict(row) if row else None


def search_articles(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not query.strip():
        return []
    pattern = f"%{query.strip().lower()}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT canonical_url, title, source, url, published_at,
                   featured_in, seen_count, last_seen_at
            FROM articles
            WHERE lower(title) LIKE ? OR lower(summary) LIKE ?
            ORDER BY last_seen_at DESC LIMIT ?
            """,
            (pattern, pattern, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def trending_topics(days: int = 7, top_n: int = 10) -> List[Dict[str, Any]]:
    """Topics with the highest mention count over the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT topic, SUM(mention_count) AS total
            FROM topic_mentions
            WHERE issue_date >= ?
            GROUP BY topic
            ORDER BY total DESC
            LIMIT ?
            """,
            (cutoff, int(top_n)),
        ).fetchall()
    return [{"topic": r["topic"], "mentions": r["total"]} for r in rows]


def stats() -> Dict[str, Any]:
    with _connect() as conn:
        issues = conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
        articles = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]
        featured = conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE featured_in IS NOT NULL"
        ).fetchone()["n"]
        avg_quality = conn.execute(
            "SELECT AVG(quality_score) AS q FROM issues WHERE quality_score IS NOT NULL"
        ).fetchone()["q"]
        last_issue = conn.execute(
            "SELECT MAX(issue_date) AS d FROM issues"
        ).fetchone()["d"]
    return {
        "issues_count": issues,
        "articles_seen": articles,
        "articles_featured": featured,
        "avg_quality": round(avg_quality, 2) if avg_quality else None,
        "last_issue_date": last_issue,
    }
