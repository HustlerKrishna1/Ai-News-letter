"""Tests for URL canonicalization, dedup, and ranking."""
from __future__ import annotations

from modules.process_news import canonical_url, deduplicate, rank


def test_canonical_url_strips_tracking_params():
    url = "https://www.example.com/path?utm_source=twitter&id=9&fbclid=abc#frag"
    assert canonical_url(url) == "https://example.com/path?id=9"


def test_canonical_url_preserves_non_tracking_params():
    url = "https://news.com/story?id=42&p=2"
    canon = canonical_url(url)
    assert "id=42" in canon
    assert "p=2" in canon


def test_canonical_url_normalizes_host_and_trailing_slash():
    assert canonical_url("HTTPS://WWW.Example.com/foo/") == "https://example.com/foo"


def test_canonical_url_empty_input_returns_empty():
    assert canonical_url("") == ""


def test_dedup_collapses_tracking_param_variants():
    articles = [
        {"title": "Big deal signed", "url": "https://ex.com/a?utm_source=rss",
         "source": "Reuters"},
        {"title": "Big deal signed", "url": "https://ex.com/a?utm_source=twitter",
         "source": "Other"},
    ]
    kept = deduplicate(articles)
    assert len(kept) == 1


def test_dedup_prefers_higher_quality_source():
    articles = [
        {"title": "Fed hikes rates", "url": "https://blog.random.io/story",
         "source": "random"},
        {"title": "Fed hikes rates", "url": "https://www.reuters.com/story",
         "source": "Reuters"},
    ]
    kept = deduplicate(articles)
    assert len(kept) == 1
    assert "reuters.com" in kept[0]["url"]


def test_dedup_preserves_distinct_stories():
    articles = [
        {"title": "AI chip startup files for IPO",
         "url": "https://techcrunch.com/ai-chip", "source": "TC"},
        {"title": "Fed signals rate pause",
         "url": "https://wsj.com/fed-pause", "source": "WSJ"},
    ]
    kept = deduplicate(articles)
    assert len(kept) == 2


def test_rank_orders_by_score_desc():
    articles = [
        {"title": "Random weather update",
         "url": "https://ex.com/w", "source": "ex", "summary": ""},
        {"title": "OpenAI announces new model",
         "url": "https://reuters.com/openai", "source": "Reuters",
         "summary": "AI model release affects industry."},
    ]
    ranked = rank(articles)
    assert ranked[0]["title"].startswith("OpenAI")
    assert ranked[0]["score"] > ranked[1]["score"]
