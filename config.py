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
# Note: HN is handled by the dedicated fetcher now, not listed here.
DEFAULT_RSS_FEEDS: List[str] = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.ft.com/technology?format=rss",
    "https://www.economist.com/finance-and-economics/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",
]

DEFAULT_REDDIT_SUBS: List[str] = [
    "technology", "artificial", "singularity", "MachineLearning",
    "worldnews", "Economics", "stocks", "geopolitics",
]


@dataclass(frozen=True)
class Settings:
    # Project paths
    project_root: Path = Path(__file__).resolve().parent
    data_dir: Path = Path(__file__).resolve().parent / "data"
    output_dir: Path = Path(__file__).resolve().parent / "output"

    # Ingestion — RSS
    rss_feeds: List[str] = field(default_factory=lambda: _get_list("RSS_FEEDS", DEFAULT_RSS_FEEDS))

    # Ingestion — NewsAPI
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    newsapi_query: str = os.getenv(
        "NEWSAPI_QUERY",
        "(AI OR \"artificial intelligence\") OR economy OR capitalism OR geopolitics OR startup",
    )
    newsapi_language: str = os.getenv("NEWSAPI_LANGUAGE", "en")
    newsapi_page_size: int = int(os.getenv("NEWSAPI_PAGE_SIZE", "40"))

    # Ingestion — Hacker News
    hn_enabled: bool = _get_bool("HN_ENABLED", True)
    hn_top_count: int = int(os.getenv("HN_TOP_COUNT", "30"))
    hn_min_score: int = int(os.getenv("HN_MIN_SCORE", "50"))

    # Ingestion — Reddit
    reddit_enabled: bool = _get_bool("REDDIT_ENABLED", True)
    reddit_subs: List[str] = field(default_factory=lambda: _get_list("REDDIT_SUBS", DEFAULT_REDDIT_SUBS))
    reddit_min_score: int = int(os.getenv("REDDIT_MIN_SCORE", "100"))
    reddit_per_sub: int = int(os.getenv("REDDIT_PER_SUB", "10"))

    # Ingestion — general
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

    # Email delivery: "smtp" | "sendgrid" | ""
    email_provider: str = os.getenv("EMAIL_PROVIDER", "").lower()
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_to: List[str] = field(default_factory=lambda: _get_list("EMAIL_TO", []))
    email_subject_prefix: str = os.getenv("EMAIL_SUBJECT_PREFIX", "Signal Brief")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_tls: bool = _get_bool("SMTP_USE_TLS", True)
    sendgrid_api_key: str = os.getenv("SENDGRID_API_KEY", "")

    # Web UI
    webui_host: str = os.getenv("WEBUI_HOST", "127.0.0.1")
    webui_port: int = int(os.getenv("WEBUI_PORT", "8000"))


settings = Settings()

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
