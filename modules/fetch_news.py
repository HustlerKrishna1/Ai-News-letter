"""Data ingestion layer.

Fetches news articles from multiple sources:
  * NewsAPI (https://newsapi.org/) — used if NEWSAPI_KEY is set.
  * RSS feeds — always available; works without any API keys.
  * Hacker News (Firebase API) — top stories above a score threshold.
  * Reddit (public JSON) — top posts from configured subreddits.

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

USER_AGENT = "newsletter-ai/2.0 (+https://github.com/HustlerKrishna1/Ai-News-letter)"
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
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _epoch_to_iso(epoch: float | int | None) -> str:
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return ""


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


def fetch_hackernews() -> List[Dict]:
    """Top HN stories above a score threshold, via the Firebase API.

    Skips Ask HN / Show HN text-only posts (no URL)."""
    if not settings.hn_enabled:
        return []
    try:
        top_ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=settings.http_timeout,
            headers={"User-Agent": USER_AGENT},
        ).json()[: settings.hn_top_count]
    except (requests.RequestException, ValueError) as exc:
        log.warning("HN topstories fetch failed: %s", exc)
        return []

    articles: List[Dict] = []
    for sid in top_ids:
        try:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=settings.http_timeout,
                headers={"User-Agent": USER_AGENT},
            ).json()
        except (requests.RequestException, ValueError):
            continue
        if not item or item.get("type") != "story":
            continue
        url = item.get("url")
        if not url:
            continue
        score = int(item.get("score") or 0)
        if score < settings.hn_min_score:
            continue
        articles.append({
            "title": (item.get("title") or "").strip(),
            "summary": f"HN score {score} · {item.get('descendants') or 0} comments",
            "source": f"Hacker News ({_host(url)})",
            "url": url,
            "published_at": _epoch_to_iso(item.get("time")),
        })
    log.info("Hacker News returned %d stories (min score %d).",
             len(articles), settings.hn_min_score)
    return articles


def fetch_reddit() -> List[Dict]:
    """Top posts from configured subreddits via the public JSON endpoint."""
    if not settings.reddit_enabled:
        return []
    articles: List[Dict] = []
    for sub in settings.reddit_subs:
        url = f"https://www.reddit.com/r/{sub}/top.json"
        try:
            resp = requests.get(
                url,
                params={"t": "day", "limit": settings.reddit_per_sub},
                timeout=settings.http_timeout,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Reddit /r/%s failed: %s", sub, exc)
            continue

        for child in payload.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("is_self") or post.get("stickied"):
                continue
            link = post.get("url_overridden_by_dest") or post.get("url")
            if not link or link.startswith("/r/"):
                continue
            score = int(post.get("score") or 0)
            if score < settings.reddit_min_score:
                continue
            articles.append({
                "title": (post.get("title") or "").strip(),
                "summary": (
                    f"r/{sub} · {score} upvotes · {post.get('num_comments', 0)} comments"
                ),
                "source": f"Reddit r/{sub}",
                "url": link,
                "published_at": _epoch_to_iso(post.get("created_utc")),
            })
        log.info("Reddit /r/%s contributed to pool.", sub)
    log.info("Reddit returned %d posts total.", len(articles))
    return articles


def fetch_all() -> List[Dict]:
    """Fetch from every configured source and concatenate."""
    collected = (
        fetch_newsapi()
        + fetch_rss()
        + fetch_hackernews()
        + fetch_reddit()
    )
    cleaned = [a for a in collected if a.get("title") and a.get("url")]
    log.info("Total raw articles fetched: %d", len(cleaned))
    return cleaned
