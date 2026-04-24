"""Full-text article enrichment.

Fetches the raw HTML of the top-N articles and extracts the main body text
using a simple density-based heuristic. Stdlib-only (no readability-lxml,
no BeautifulSoup) so the core dependency surface stays tiny.

The heuristic: for each <p> tag, count text length outside of tags. Boilerplate
nav/footer blocks produce short runs; article bodies produce long runs. We
concatenate long runs that appear in document order.

If extraction fails or yields nothing useful, we fall back to the summary
field so downstream code never sees None.
"""
from __future__ import annotations

import concurrent.futures
import html
import logging
import re
from html.parser import HTMLParser
from typing import Dict, List

import requests

from config import settings
from modules.retry import with_retry

log = logging.getLogger(__name__)

USER_AGENT = "newsletter-ai/3.0 (+https://github.com/HustlerKrishna1/Ai-News-letter)"

_SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "form", "noscript",
              "iframe", "svg", "button", "header"}


class _Extractor(HTMLParser):
    """Collect text from <p> tags outside obvious boilerplate containers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_para = 0
        self._current: List[str] = []
        self.paragraphs: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "p":
            self._in_para += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "p" and self._in_para:
            self._in_para -= 1
            text = " ".join(self._current).strip()
            self._current = []
            if text:
                self.paragraphs.append(text)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._in_para:
            return
        cleaned = re.sub(r"\s+", " ", data)
        if cleaned.strip():
            self._current.append(cleaned)


@with_retry(attempts=2, base_delay=0.3)
def _fetch_html(url: str, timeout: int) -> str:
    resp = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        },
        allow_redirects=True,
    )
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype.lower() and "xml" not in ctype.lower():
        raise ValueError(f"non-HTML content-type: {ctype}")
    return resp.text


def extract_text(html_text: str, min_para_chars: int = 60,
                 max_chars: int = 6000) -> str:
    """Pull the main body text out of an HTML document."""
    parser = _Extractor()
    try:
        parser.feed(html_text)
    except Exception as exc:
        log.debug("HTMLParser error: %s", exc)
        return ""

    body_paras = [p for p in parser.paragraphs if len(p) >= min_para_chars]
    if not body_paras:
        return ""

    joined = "\n\n".join(body_paras)
    return joined[:max_chars]


def enrich_articles(articles: List[Dict], top_n: int = 15) -> List[Dict]:
    """Attach a `full_text` field to the top-N ranked articles.

    Articles that fail extraction keep an empty string; downstream code
    should fall back to `summary` when `full_text` is empty.
    """
    if top_n <= 0 or not articles:
        return articles
    to_enrich = articles[:top_n]

    def _worker(art: Dict) -> tuple[Dict, str]:
        url = art.get("url", "")
        if not url:
            return art, ""
        try:
            html_text = _fetch_html(url, timeout=settings.http_timeout)
        except (requests.RequestException, ValueError) as exc:
            log.debug("Enrichment failed for %s: %s", url, exc)
            return art, ""
        return art, extract_text(html_text)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_worker, to_enrich))

    enriched_count = 0
    for art, text in results:
        art["full_text"] = text
        if text:
            enriched_count += 1
    log.info("Enriched %d/%d articles with full text.", enriched_count, len(to_enrich))
    return articles
