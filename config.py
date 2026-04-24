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
    if raw is None:
        return default
    if not raw.strip():
        return []
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
]

DEFAULT_REDDIT_SUBS: List[str] = [
    "technology", "artificial", "singularity", "MachineLearning",
    "worldnews", "Economics", "stocks", "geopolitics",
]

DEFAULT_ARXIV_CATEGORIES: List[str] = ["cs.AI", "cs.LG", "cs.CL"]

DEFAULT_GITHUB_LANGS: List[str] = ["", "python", "typescript"]


@dataclass(frozen=True)
class Settings:
    # Project paths
    project_root: Path = Path(__file__).resolve().parent
    data_dir: Path = Path(__file__).resolve().parent / "data"
    output_dir: Path = Path(__file__).resolve().parent / "output"

    # --- Ingestion: RSS ---
    rss_feeds: List[str] = field(default_factory=lambda: _get_list("RSS_FEEDS", DEFAULT_RSS_FEEDS))

    # --- Ingestion: NewsAPI ---
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    newsapi_query: str = os.getenv(
        "NEWSAPI_QUERY",
        "(AI OR \"artificial intelligence\") OR economy OR capitalism OR geopolitics OR startup",
    )
    newsapi_language: str = os.getenv("NEWSAPI_LANGUAGE", "en")
    newsapi_page_size: int = int(os.getenv("NEWSAPI_PAGE_SIZE", "40"))

    # --- Ingestion: Hacker News ---
    hn_enabled: bool = _get_bool("HN_ENABLED", True)
    hn_top_count: int = int(os.getenv("HN_TOP_COUNT", "30"))
    hn_min_score: int = int(os.getenv("HN_MIN_SCORE", "50"))

    # --- Ingestion: Reddit ---
    reddit_enabled: bool = _get_bool("REDDIT_ENABLED", True)
    reddit_subs: List[str] = field(default_factory=lambda: _get_list("REDDIT_SUBS", DEFAULT_REDDIT_SUBS))
    reddit_min_score: int = int(os.getenv("REDDIT_MIN_SCORE", "100"))
    reddit_per_sub: int = int(os.getenv("REDDIT_PER_SUB", "10"))

    # --- Ingestion: arXiv ---
    arxiv_enabled: bool = _get_bool("ARXIV_ENABLED", True)
    arxiv_categories: List[str] = field(
        default_factory=lambda: _get_list("ARXIV_CATEGORIES", DEFAULT_ARXIV_CATEGORIES)
    )
    arxiv_max_results: int = int(os.getenv("ARXIV_MAX_RESULTS", "25"))

    # --- Ingestion: GitHub Trending ---
    github_trending_enabled: bool = _get_bool("GITHUB_TRENDING_ENABLED", True)
    github_trending_languages: List[str] = field(
        default_factory=lambda: _get_list("GITHUB_TRENDING_LANGUAGES", DEFAULT_GITHUB_LANGS)
    )
    github_trending_per_lang: int = int(os.getenv("GITHUB_TRENDING_PER_LANG", "8"))
    github_trending_since: str = os.getenv("GITHUB_TRENDING_SINCE", "daily")

    # --- Ingestion: general ---
    max_articles_per_source: int = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "15"))
    max_total_articles: int = int(os.getenv("MAX_TOTAL_ARTICLES", "40"))
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "15"))

    # --- Enrichment ---
    enrich_top_n: int = int(os.getenv("ENRICH_TOP_N", "15"))
    enrich_enabled: bool = _get_bool("ENRICH_ENABLED", True)

    # --- Cross-run dedup ---
    cross_run_dedup: bool = _get_bool("CROSS_RUN_DEDUP", True)
    cross_run_dedup_days: int = int(os.getenv("CROSS_RUN_DEDUP_DAYS", "14"))

    # --- Editorial pipeline ---
    editorial_pick_limit: int = int(os.getenv("EDITORIAL_PICK_LIMIT", "15"))
    editorial_parallel_sections: int = int(os.getenv("EDITORIAL_PARALLEL_SECTIONS", "4"))
    critique_enabled: bool = _get_bool("CRITIQUE_ENABLED", True)
    critique_regenerate_below: float = float(os.getenv("CRITIQUE_REGENERATE_BELOW", "6.0"))

    # --- LLM providers ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))

    # --- Output ---
    emit_html: bool = _get_bool("EMIT_HTML", True)

    # --- Delivery: email ---
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

    # --- Delivery: chat platforms ---
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Comma-separated list of channels: any of email,slack,discord,telegram
    delivery_channels: List[str] = field(
        default_factory=lambda: _get_list("DELIVERY_CHANNELS", [])
    )

    # Public base URL of the dashboard (for RSS `<link>` + webhook CTAs).
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")

    # --- Web UI ---
    webui_host: str = os.getenv("WEBUI_HOST", "127.0.0.1")
    webui_port: int = int(os.getenv("WEBUI_PORT", "8000"))


settings = Settings()

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
