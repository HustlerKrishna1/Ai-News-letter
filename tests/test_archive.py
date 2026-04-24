"""Tests for the SQLite archive."""
from __future__ import annotations

from modules import archive
from modules.process_news import canonical_url


def test_init_creates_tables():
    archive.init()
    s = archive.stats()
    assert s["issues_count"] == 0
    assert s["articles_seen"] == 0


def test_upsert_and_mark_featured():
    archive.init()
    articles = [
        {"title": "Story A", "url": "https://ex.com/a?utm_source=x",
         "source": "Reuters", "summary": "…", "published_at": ""},
        {"title": "Story B", "url": "https://ex.com/b",
         "source": "WSJ", "summary": "…", "published_at": ""},
    ]
    archive.upsert_articles(articles, canonical_url)
    assert archive.stats()["articles_seen"] == 2

    archive.upsert_articles(articles, canonical_url)  # idempotent on canonical_url
    assert archive.stats()["articles_seen"] == 2

    canon_a = canonical_url("https://ex.com/a")
    archive.mark_featured([canon_a], "2026-04-22")
    featured = archive.already_featured([canon_a])
    assert canon_a in featured


def test_record_and_list_issues():
    archive.init()
    archive.record_issue({
        "issue_date": "2026-04-22",
        "subject": "Test issue",
        "markdown_path": "/tmp/test.md",
        "html_path": "/tmp/test.html",
        "article_count": 12,
        "cluster_count": 3,
        "llm_provider": "MockClient",
        "llm_ms": 1234,
        "quality_score": 7.5,
        "critique": {"scores": {"clarity": 8}, "overall": 7.5},
    })
    issues = archive.list_issues()
    assert len(issues) == 1
    assert issues[0]["subject"] == "Test issue"
    assert issues[0]["quality_score"] == 7.5

    got = archive.get_issue("2026-04-22")
    assert got and got["subject"] == "Test issue"


def test_trending_topics_aggregates_across_issues():
    archive.init()
    archive.record_topic_counts("2026-04-20", {"AI": 4, "Economy": 2})
    archive.record_topic_counts("2026-04-21", {"AI": 3, "Geopolitics": 5})
    trending = archive.trending_topics(days=30, top_n=5)
    names = {t["topic"]: t["mentions"] for t in trending}
    assert names["AI"] == 7
    assert names["Geopolitics"] == 5


def test_search_matches_title_case_insensitive():
    archive.init()
    archive.upsert_articles(
        [{"title": "Nvidia Earnings beat", "url": "https://ex.com/n",
          "source": "Reuters", "summary": "", "published_at": ""}],
        canonical_url,
    )
    hits = archive.search_articles("nvidia")
    assert len(hits) == 1
    assert "Nvidia" in hits[0]["title"]
