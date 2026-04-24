"""Extra sources: arXiv (research papers) and GitHub Trending.

These surface signal that mainstream RSS misses — fresh AI research and
what open-source developers are actually building this week.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List

import requests

from config import settings
from modules.retry import with_retry

log = logging.getLogger(__name__)

USER_AGENT = "newsletter-ai/3.0 (+https://github.com/HustlerKrishna1/Ai-News-letter)"


@with_retry(attempts=2, base_delay=0.5)
def _http_get(url: str, params: Dict | None = None) -> requests.Response:
    resp = requests.get(
        url, params=params,
        timeout=settings.http_timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml,text/html,*/*"},
    )
    resp.raise_for_status()
    return resp


def fetch_arxiv() -> List[Dict]:
    """Recent submissions to cs.AI / cs.LG / cs.CL on arXiv.

    Uses the arXiv Atom API. No auth required. See https://arxiv.org/help/api.
    """
    if not settings.arxiv_enabled:
        return []

    category_query = " OR ".join(f"cat:{c}" for c in settings.arxiv_categories)
    params = {
        "search_query": f"({category_query})",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": settings.arxiv_max_results,
    }
    try:
        resp = _http_get("https://export.arxiv.org/api/query", params=params)
    except requests.RequestException as exc:
        log.warning("arXiv fetch failed: %s", exc)
        return []

    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        log.warning("arXiv parse failed: %s", exc)
        return []

    articles: List[Dict] = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", namespaces=ns) or "").strip()
        title = re.sub(r"\s+", " ", title)
        summary = (entry.findtext("a:summary", namespaces=ns) or "").strip()
        summary = re.sub(r"\s+", " ", summary)
        published = (entry.findtext("a:published", namespaces=ns) or "").strip()

        link_url = ""
        for link in entry.findall("a:link", ns):
            if link.get("rel") == "alternate" or link.get("type") == "text/html":
                link_url = link.get("href", "")
                break
        if not link_url or not title:
            continue

        authors = [
            (a.findtext("a:name", namespaces=ns) or "").strip()
            for a in entry.findall("a:author", ns)
        ]
        author_note = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

        articles.append({
            "title": f"[arXiv] {title}",
            "summary": (f"{author_note}. " if author_note else "") + summary[:600],
            "source": "arXiv",
            "url": link_url,
            "published_at": _iso(published),
        })
    log.info("arXiv returned %d papers.", len(articles))
    return articles


def _iso(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


_GH_TITLE_RE = re.compile(
    r'<h2[^>]*class="[^"]*h3[^"]*"[^>]*>.*?<a[^>]+href="(/[^"]+)"', re.DOTALL
)
_GH_DESC_RE = re.compile(
    r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', re.DOTALL
)
_GH_STARS_RE = re.compile(
    r'<span[^>]*d-inline-block[^>]*fgColor-default[^>]*>\s*<svg[^>]*octicon-star'
    r'[^>]*>.*?</svg>\s*([\d,]+)', re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")


def fetch_github_trending() -> List[Dict]:
    """Today's trending repositories on GitHub.

    GitHub doesn't expose an API for Trending, so we lightly scrape the
    public HTML page. Scraping is OK here because the page is rendered
    server-side and stable; we also degrade gracefully on HTML changes.
    """
    if not settings.github_trending_enabled:
        return []

    articles: List[Dict] = []
    for lang in settings.github_trending_languages or [""]:
        url = "https://github.com/trending"
        if lang:
            url += f"/{lang}"
        url += f"?since={settings.github_trending_since}"
        try:
            resp = _http_get(url)
        except requests.RequestException as exc:
            log.warning("GitHub Trending (%s) failed: %s", lang or "all", exc)
            continue

        html_text = resp.text
        # Split on repo cards to keep per-repo regex scoped.
        cards = re.split(r'<article class="Box-row">', html_text)[1:]
        for card in cards[: settings.github_trending_per_lang]:
            title_m = re.search(r'<a[^>]+href="(/[^"]+)"', card)
            if not title_m:
                continue
            slug = title_m.group(1).strip()
            if slug.count("/") < 2 and not slug.startswith("/"):
                continue
            slug = slug.strip("/")
            desc_m = re.search(r'<p[^>]*>(.*?)</p>', card, re.DOTALL)
            desc = _TAG.sub("", desc_m.group(1)).strip() if desc_m else ""
            desc = re.sub(r"\s+", " ", desc)

            stars_m = re.search(r'>\s*([\d,]+)\s*stars today', card)
            stars_today = stars_m.group(1) if stars_m else "?"

            articles.append({
                "title": f"[GitHub] {slug}",
                "summary": f"{stars_today} stars today" + (f" — {desc}" if desc else ""),
                "source": f"GitHub Trending ({lang or 'all'})",
                "url": f"https://github.com/{slug}",
                "published_at": datetime.now(timezone.utc).isoformat(),
            })
    log.info("GitHub Trending returned %d repos.", len(articles))
    return articles
