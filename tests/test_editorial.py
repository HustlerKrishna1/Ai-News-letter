"""Tests for the multi-stage editorial pipeline (mock provider)."""
from __future__ import annotations

from modules.editorial import EditorialMockClient, run_editorial


def _make(i: int, theme: str = "ai") -> dict:
    return {
        "title": f"{theme.upper()} story number {i}",
        "summary": f"Details about {theme} story {i} and its consequences for the sector.",
        "source": "TestSource",
        "url": f"https://ex.com/{theme}/{i}",
        "published_at": "",
        "score": 10.0 - i * 0.1,
    }


def test_mock_client_routes_by_stage_marker():
    client = EditorialMockClient()
    triage = client.generate("[stage:triage]", "[1] a\n[2] b\n[3] c\nPick the top 2")
    assert '"selected"' in triage
    section = client.generate("[stage:section]", "- Story X (src)\n  text")
    assert len(section) > 50
    subject = client.generate("[stage:subject]", "Today something happened in AI.")
    assert subject.startswith("Signal Brief")
    critique = client.generate("[stage:critique]", "draft body")
    assert '"scores"' in critique


def test_run_editorial_end_to_end_with_mock():
    articles = [_make(i, theme="ai") for i in range(8)] + [
        _make(i, theme="economy") for i in range(4)
    ]
    result = run_editorial(articles, trending=[{"topic": "AI", "mentions": 4}])
    assert result["body"]
    assert "##" in result["body"]
    assert result["subject"]
    assert result["provider"]
    assert isinstance(result["llm_ms"], int) and result["llm_ms"] >= 0
    assert len(result["featured"]) > 0
    assert len(result["clusters"]) >= 1


def test_run_editorial_empty_input_degrades_gracefully():
    result = run_editorial([])
    assert result["body"]
    assert "no signal" in result["subject"].lower() or "no" in result["body"].lower()
    assert result["featured"] == []
