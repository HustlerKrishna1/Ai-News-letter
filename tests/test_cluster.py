"""Tests for topic clustering."""
from __future__ import annotations

from modules.cluster import cluster_articles


def _make(title: str, summary: str = "") -> dict:
    return {
        "title": title,
        "summary": summary,
        "url": f"https://ex.com/{abs(hash(title))}",
        "source": "test",
    }


def test_cluster_groups_related_ai_stories():
    articles = [
        _make("OpenAI launches GPT-5", "OpenAI released a new GPT model."),
        _make("Anthropic raises Series E", "Anthropic closed a funding round."),
        _make("Nvidia chip demand surges", "Nvidia GPU demand hits records."),
        _make("Cerebras files for IPO", "Cerebras AI chip maker files IPO papers."),
        _make("Fed holds rates steady", "The Federal Reserve kept interest rates flat."),
        _make("Inflation ticks up in Eurozone", "CPI data shows inflation rising."),
    ]
    clusters = cluster_articles(articles, similarity_threshold=0.1, min_cluster_size=2)
    assert len(clusters) >= 1
    # Every article should land in exactly one cluster.
    total = sum(len(c["articles"]) for c in clusters)
    assert total == len(articles)


def test_cluster_empty_input():
    assert cluster_articles([]) == []


def test_cluster_singletons_merge_into_other():
    articles = [
        _make("Random topic A unique words xyz"),
        _make("Random topic B different unique pqr"),
        _make("Random topic C yet-more-unique terms mnb"),
    ]
    clusters = cluster_articles(articles, similarity_threshold=0.5, min_cluster_size=2)
    # With no overlap, all three collapse into the Other Signals bucket.
    assert any(c["name"] == "Other Signals" for c in clusters)


def test_cluster_names_are_human_readable():
    # Three macro-economy articles with enough shared terms to actually cluster.
    articles = [
        _make("Fed holds interest rates steady",
              "The Federal Reserve kept interest rates unchanged amid inflation pressure "
              "and mixed earnings across stocks and bonds."),
        _make("Markets react to Fed rate decision",
              "Stocks and bonds moved after the Fed held interest rates steady; "
              "inflation concerns weigh on earnings expectations."),
        _make("Inflation ticks up as earnings disappoint",
              "Market inflation indicators rose while Fed watchers parsed rate "
              "guidance; stocks and bonds volatile on earnings data."),
    ]
    clusters = cluster_articles(articles, similarity_threshold=0.1, min_cluster_size=2)
    # At least one cluster should land on the "Markets & Economy" theme label.
    assert any(
        ("Market" in c["name"] or "Economy" in c["name"])
        for c in clusters
    ), f"clusters were: {[c['name'] for c in clusters]}"
