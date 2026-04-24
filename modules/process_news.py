"""Signal processing layer.

Deduplicates articles, scores them by topical relevance + source quality +
recency, and returns the top-N most relevant items.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from config import settings

log = logging.getLogger(__name__)

# Keyword weights drive topical relevance scoring. Higher = stronger signal.
KEYWORD_WEIGHTS: Dict[str, float] = {
    # AI / tech
    "ai": 3.0, "artificial intelligence": 4.0, "llm": 3.5, "gpt": 2.5,
    "openai": 3.0, "anthropic": 3.0, "nvidia": 2.5, "chip": 1.5,
    "model": 1.0, "agent": 2.0, "automation": 1.5, "robotics": 2.0,
    # Economy / capitalism
    "economy": 2.5, "inflation": 2.5, "recession": 3.0, "fed": 2.5,
    "interest rate": 2.5, "markets": 1.5, "earnings": 1.5, "ipo": 2.0,
    "capitalism": 3.0, "monopoly": 2.0, "antitrust": 2.0,
    # Geopolitics / power shifts
    "china": 2.0, "russia": 1.5, "europe": 1.0, "election": 2.0,
    "tariff": 2.0, "sanction": 2.0, "geopolitic": 3.0, "power": 1.0,
    # Startup / capital
    "startup": 2.0, "venture": 2.0, "funding": 1.5, "acquisition": 2.0,
}

# Reputable sources get a small quality boost.
SOURCE_QUALITY: Dict[str, float] = {
    "reuters.com": 1.5, "wsj.com": 1.5, "ft.com": 1.5, "bloomberg.com": 1.5,
    "economist.com": 1.5, "nytimes.com": 1.2, "arstechnica.com": 1.0,
    "wired.com": 1.0, "techcrunch.com": 0.8, "ycombinator.com": 0.8,
}

_WORD_RE = re.compile(r"[a-z0-9]+")

# Tracking params we strip during URL canonicalization. Dropping these means
# two links to the same article with different utm_* tails collapse to one.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "gclid", "fbclid", "mc_cid", "mc_eid",
    "ref", "ref_src", "ref_url", "source", "share", "__twitter_impression",
    "cmpid", "CMP", "ns_source", "ns_mchannel", "ns_campaign",
}


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def _normalize_title(title: str) -> str:
    return " ".join(_tokens(title))


def canonical_url(url: str) -> str:
    """Normalize a URL so cross-source duplicates collapse.

    - Lowercase scheme + host, strip leading 'www.'
    - Drop fragment
    - Remove tracking query params
    - Drop trailing slash on path
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
             if k.lower() not in _TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((
        (parsed.scheme or "https").lower(),
        host,
        path,
        parsed.params,
        urlencode(query, doseq=True),
        "",
    ))


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def deduplicate(articles: List[Dict]) -> List[Dict]:
    """Drop canonical-URL dupes and near-duplicate titles (Jaccard >= 0.75).

    When collapsing duplicates across sources we prefer the article whose
    source domain appears in the quality table, so Reuters wins over a
    link-aggregator that happens to point at the same story.
    """
    kept: List[Dict] = []
    canonical_index: Dict[str, int] = {}

    for art in articles:
        canon = canonical_url(art.get("url", ""))
        if not canon:
            continue
        norm = _normalize_title(art.get("title", ""))
        if not norm:
            continue

        if canon in canonical_index:
            existing_idx = canonical_index[canon]
            if _prefer(art, kept[existing_idx]):
                kept[existing_idx] = art
            continue

        dup_idx = _title_dup_index(norm, kept)
        if dup_idx is not None:
            if _prefer(art, kept[dup_idx]):
                kept[dup_idx] = art
                canonical_index[canon] = dup_idx
            continue

        canonical_index[canon] = len(kept)
        kept.append(art)

    log.info("Deduplication: %d -> %d", len(articles), len(kept))
    return kept


def _title_dup_index(norm_title: str, kept: List[Dict]) -> int | None:
    for i, k in enumerate(kept):
        if _jaccard(norm_title, _normalize_title(k["title"])) >= 0.75:
            return i
    return None


def _prefer(candidate: Dict, incumbent: Dict) -> bool:
    """Return True if candidate should replace incumbent as canonical."""
    return _domain_rank(candidate.get("url", "")) > _domain_rank(incumbent.get("url", ""))


def _domain_rank(url: str) -> float:
    host = urlparse(url).netloc.lower().lstrip("www.")
    for domain, boost in SOURCE_QUALITY.items():
        if domain in host:
            return boost
    return 0.0


def _recency_bonus(published_at: str) -> float:
    if not published_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return 0.0
    hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    if hours < 0:
        return 1.0
    if hours < 12:
        return 2.0
    if hours < 24:
        return 1.5
    if hours < 48:
        return 1.0
    if hours < 96:
        return 0.5
    return 0.0


def score_article(article: Dict) -> float:
    haystack = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    relevance = 0.0
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword in haystack:
            relevance += weight

    host = urlparse(article.get("url", "")).netloc.lower().lstrip("www.")
    quality = 0.0
    for domain, boost in SOURCE_QUALITY.items():
        if domain in host:
            quality = boost
            break

    # Light penalty for very short summaries (low information density).
    length_bonus = min(len(article.get("summary", "")) / 400.0, 1.5)

    return relevance + quality + length_bonus + _recency_bonus(article.get("published_at", ""))


def rank(articles: List[Dict], limit: int | None = None) -> List[Dict]:
    """Score, sort (desc), and optionally truncate the article list."""
    scored: List[Tuple[float, Dict]] = [(score_article(a), a) for a in articles]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = []
    for score, art in scored:
        art = {**art, "score": round(score, 2)}
        ranked.append(art)
    if limit:
        ranked = ranked[:limit]
    return ranked


def _drop_already_featured(articles: List[Dict]) -> List[Dict]:
    """Drop articles that were featured in a recent issue.

    Import the archive lazily so `process()` stays usable in tests and
    environments where the archive isn't initialized.
    """
    if not settings.cross_run_dedup:
        return articles
    try:
        from modules import archive  # local import to avoid circularity at import time

        archive.init()
        canons = [canonical_url(a.get("url", "")) for a in articles]
        recent = archive.already_featured(canons, within_days=settings.cross_run_dedup_days)
    except Exception as exc:  # noqa: BLE001 - archive must not break pipeline
        log.warning("Cross-run dedup skipped (archive error): %s", exc)
        return articles
    if not recent:
        return articles
    filtered = [a for a in articles
                if canonical_url(a.get("url", "")) not in recent]
    dropped = len(articles) - len(filtered)
    if dropped:
        log.info("Cross-run dedup dropped %d previously-featured article(s) "
                 "(window: %d days)", dropped, settings.cross_run_dedup_days)
    return filtered


def process(articles: List[Dict]) -> List[Dict]:
    """Full processing pipeline: dedupe -> cross-run dedup -> rank -> cap."""
    deduped = deduplicate(articles)
    fresh = _drop_already_featured(deduped)
    ranked = rank(fresh, limit=settings.max_total_articles)
    log.info("Processed down to %d ranked articles.", len(ranked))
    return ranked
