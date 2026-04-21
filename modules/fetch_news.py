"""Data ingestion layer.

Fetches news articles from two sources:
  * NewsAPI (https://newsapi.org/) — used if NEWSAPI_KEY is set.
  * RSS feeds — always available; works without any API keys.

Returns a list of normalized article dicts:
    {
        "title": str,
        "summary": str,
        "source": str,
        "url": str,
        "published_at": str (ISO8601 or ""),
    }
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List
from urllib.parse import urlparse

import requests

from config import settings

log = logging.getLogger(__name__)

USER_AGENT = "newsletter-ai/1.0 (+https://example.local)"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text)).strip()


def _normalize_dt(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except ValueError:
        return "unknown"


def fetch_newsapi() -> List[Dict]:
    """Fetch top headlines from NewsAPI. Returns [] if no key configured."""
    if not settings.newsapi_key:
        log.info("NEWSAPI_KEY not set; skipping NewsAPI ingestion.")
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": settings.newsapi_query,
        "language": settings.newsapi_language,
        "sortBy": "publishedAt",
        "pageSize": settings.newsapi_page_size,
        "apiKey": settings.newsapi_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=settings.http_timeout,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("NewsAPI request failed: %s", exc)
        return []

    payload = resp.json()
    articles = []
    for item in payload.get("articles", []):
        articles.append({
            "title": (item.get("title") or "").strip(),
            "summary": _strip_html(item.get("description") or item.get("content") or ""),
            "source": (item.get("source") or {}).get("name") or _host(item.get("url", "")),
            "url": item.get("url") or "",
            "published_at": _normalize_dt(item.get("publishedAt")),
        })
    log.info("NewsAPI returned %d articles.", len(articles))
    return articles


def _parse_rss(xml_text: str, feed_url: str) -> List[Dict]:
    """Parse RSS 2.0 or Atom feeds using stdlib ElementTree."""
    articles: List[Dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("Could not parse feed %s: %s", feed_url, exc)
        return articles

    # RSS 2.0
    channel = root.find("channel")
    source_name = _host(feed_url)
    if channel is not None:
        ch_title = channel.findtext("title")
        if ch_title:
            source_name = ch_title.strip()
        for item in channel.findall("item"):
            articles.append({
                "title": _strip_html(item.findtext("title") or ""),
                "summary": _strip_html(item.findtext("description") or ""),
                "source": source_name,
                "url": (item.findtext("link") or "").strip(),
                "published_at": _normalize_dt(item.findtext("pubDate")),
            })
        return articles

    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    if root.tag.endswith("feed"):
        src = root.findtext("a:title", namespaces=ns)
        if src:
            source_name = src.strip()
        for entry in root.findall("a:entry", ns):
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            articles.append({
                "title": _strip_html(entry.findtext("a:title", namespaces=ns) or ""),
                "summary": _strip_html(
                    entry.findtext("a:summary", namespaces=ns)
                    or entry.findtext("a:content", namespaces=ns)
                    or ""
                ),
                "source": source_name,
                "url": link,
                "published_at": _normalize_dt(
                    entry.findtext("a:updated", namespaces=ns)
                    or entry.findtext("a:published", namespaces=ns)
                ),
            })
    return articles


def fetch_rss(feeds: Iterable[str] | None = None) -> List[Dict]:
    feeds = list(feeds or settings.rss_feeds)
    results: List[Dict] = []
    for feed in feeds:
        try:
            resp = requests.get(feed, timeout=settings.http_timeout,
                                headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Feed %s failed: %s", feed, exc)
            continue
        parsed = _parse_rss(resp.text, feed)[: settings.max_articles_per_source]
        log.info("Feed %s -> %d articles", feed, len(parsed))
        results.extend(parsed)
    return results


def fetch_all() -> List[Dict]:
    """Fetch from every configured source and concatenate."""
    collected = fetch_newsapi() + fetch_rss()
    # Drop entries missing a title or url
    cleaned = [a for a in collected if a.get("title") and a.get("url")]
    log.info("Total raw articles fetched: %d", len(cleaned))
    return cleaned
