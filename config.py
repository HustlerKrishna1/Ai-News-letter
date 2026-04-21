"""Central configuration for the newsletter generator.

Reads environment variables from a `.env` file (if present) and exposes
typed constants used across the pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env from project root (if present). Safe to call even if file is missing.
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# Default RSS feeds covering AI, economy, capitalism, geopolitics.
DEFAULT_RSS_FEEDS: List[str] = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.ft.com/technology?format=rss",
    "https://www.economist.com/finance-and-economics/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",
    "https://hnrss.org/frontpage",
]


@dataclass(frozen=True)
class Settings:
    # Project paths
    project_root: Path = Path(__file__).resolve().parent
    data_dir: Path = Path(__file__).resolve().parent / "data"
    output_dir: Path = Path(__file__).resolve().parent / "output"

    # Ingestion
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    newsapi_query: str = os.getenv(
        "NEWSAPI_QUERY",
        "(AI OR \"artificial intelligence\") OR economy OR capitalism OR geopolitics OR startup",
    )
    newsapi_language: str = os.getenv("NEWSAPI_LANGUAGE", "en")
    newsapi_page_size: int = int(os.getenv("NEWSAPI_PAGE_SIZE", "40"))
    rss_feeds: List[str] = field(default_factory=lambda: _get_list("RSS_FEEDS", DEFAULT_RSS_FEEDS))
    max_articles_per_source: int = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "15"))
    max_total_articles: int = int(os.getenv("MAX_TOTAL_ARTICLES", "40"))
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "15"))

    # LLM provider: "anthropic" | "openai" | "mock"
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))

    # Output
    emit_html: bool = _get_bool("EMIT_HTML", True)


settings = Settings()

# Ensure runtime directories exist.
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
