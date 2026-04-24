"""Topic clustering.

Groups related articles into thematic clusters so the newsletter has
structure (a "Section: AI Infrastructure" instead of a flat list).

Uses TF-IDF + greedy agglomerative clustering with cosine similarity. All
computations are pure-Python / stdlib — no numpy / scikit-learn dependency.

For a ~40-article input this takes a few ms, which is fine for a daily run.
The tradeoff vs. true embeddings: we miss semantic equivalents ("robotics" ≈
"autonomous systems") but gain offline determinism + zero extra deps.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Dict, List

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{2,}")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "while", "of", "in", "on", "to",
    "for", "is", "are", "was", "were", "be", "been", "being", "with", "as", "at",
    "by", "from", "this", "that", "these", "those", "it", "its", "their", "there",
    "has", "have", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "cannot", "not", "no", "nor", "so", "than", "then",
    "also", "some", "any", "all", "more", "most", "other", "such", "who", "whom",
    "what", "which", "when", "where", "why", "how", "about", "after", "before",
    "new", "news", "says", "said", "say", "one", "two", "year", "years", "day",
    "week", "month", "today", "yesterday", "tomorrow", "now", "just",
    "into", "out", "over", "under", "up", "down", "off", "per", "via", "amid",
}

# Theme labels we try to match during naming. Order matters — first hit wins.
_THEME_LABELS: List[tuple[str, tuple[str, ...]]] = [
    ("AI Infrastructure",    ("gpu", "cerebras", "datacenter", "compute", "chip", "nvidia", "tpu", "foundry")),
    ("AI Models & Research", ("model", "llm", "transformer", "diffusion", "embedding", "arxiv", "fine-tune", "gpt", "claude", "gemini")),
    ("AI Regulation",        ("regulation", "policy", "antitrust", "act", "law", "lawsuit", "court", "legal")),
    ("AI Companies",         ("openai", "anthropic", "deepmind", "mistral", "xai", "cohere", "perplexity", "hugging")),
    ("Markets & Economy",    ("market", "economy", "inflation", "recession", "fed", "rate", "earnings", "stocks", "bonds", "yield")),
    ("Geopolitics",          ("china", "russia", "taiwan", "iran", "nato", "tariff", "sanction", "treaty", "summit", "war")),
    ("Capital & VC",         ("startup", "funding", "valuation", "vc", "venture", "ipo", "acquisition", "series")),
    ("Energy & Climate",     ("energy", "oil", "nuclear", "solar", "grid", "emissions", "climate", "battery")),
    ("Crypto & Web3",        ("bitcoin", "ethereum", "crypto", "token", "defi", "stablecoin", "blockchain")),
]


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text)
            if t.lower() not in _STOPWORDS and len(t) > 2]


def _article_tokens(article: Dict) -> List[str]:
    parts = [article.get("title", ""), article.get("summary", "")]
    if article.get("full_text"):
        parts.append(article["full_text"][:2000])
    return _tokens(" ".join(parts))


def _tfidf_vectors(articles: List[Dict]) -> List[Dict[str, float]]:
    """Return one sparse tf-idf vector per article."""
    docs = [_article_tokens(a) for a in articles]
    df: Counter = Counter()
    for tokens in docs:
        df.update(set(tokens))
    n_docs = max(len(docs), 1)

    vectors: List[Dict[str, float]] = []
    for tokens in docs:
        tf = Counter(tokens)
        total = sum(tf.values()) or 1
        vec: Dict[str, float] = {}
        for term, count in tf.items():
            tf_part = count / total
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1.0
            vec[term] = tf_part * idf
        vectors.append(vec)
    return vectors


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # Iterate the smaller dict for the dot product.
    small, large = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(weight * large.get(term, 0.0) for term, weight in small.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def cluster_articles(articles: List[Dict],
                     similarity_threshold: float = 0.22,
                     min_cluster_size: int = 2) -> List[Dict]:
    """Group articles into clusters; singletons go to a single 'Other Signals' cluster.

    Returns list of cluster dicts with keys: name, articles, keywords.
    """
    if not articles:
        return []

    vectors = _tfidf_vectors(articles)
    clusters: List[Dict] = []  # each: {centroid: dict, indices: list[int]}

    for idx, vec in enumerate(vectors):
        best_cluster = -1
        best_sim = 0.0
        for ci, cluster in enumerate(clusters):
            sim = _cosine(vec, cluster["centroid"])
            if sim > best_sim:
                best_sim = sim
                best_cluster = ci
        if best_cluster >= 0 and best_sim >= similarity_threshold:
            cluster = clusters[best_cluster]
            cluster["indices"].append(idx)
            cluster["centroid"] = _merge_centroid(cluster["centroid"], vec,
                                                  len(cluster["indices"]))
        else:
            clusters.append({"centroid": dict(vec), "indices": [idx]})

    # Build output clusters: merge singletons into an 'Other Signals' bucket.
    output: List[Dict] = []
    other_indices: List[int] = []
    for cluster in clusters:
        if len(cluster["indices"]) < min_cluster_size:
            other_indices.extend(cluster["indices"])
            continue
        cluster_articles_list = [articles[i] for i in cluster["indices"]]
        top_keywords = _top_keywords(cluster["centroid"], top_n=6)
        output.append({
            "name": _label_for(top_keywords, cluster_articles_list),
            "keywords": top_keywords,
            "articles": cluster_articles_list,
        })

    if other_indices:
        cluster_articles_list = [articles[i] for i in other_indices]
        output.append({
            "name": "Other Signals",
            "keywords": _top_keywords_from_articles(cluster_articles_list, top_n=6),
            "articles": cluster_articles_list,
        })

    # Sort clusters: by article count desc, but 'Other Signals' always last.
    output.sort(key=lambda c: (c["name"] == "Other Signals", -len(c["articles"])))
    log.info("Clustered %d articles into %d groups: %s",
             len(articles), len(output),
             ", ".join(f"{c['name']}({len(c['articles'])})" for c in output))
    return output


def _merge_centroid(existing: Dict[str, float], new_vec: Dict[str, float],
                    new_count: int) -> Dict[str, float]:
    """Incrementally update a cluster centroid as the running mean."""
    merged = dict(existing)
    weight = 1.0 / new_count
    for term, value in new_vec.items():
        merged[term] = merged.get(term, 0.0) * (1 - weight) + value * weight
    for term in list(merged.keys()):
        if term not in new_vec:
            merged[term] = merged[term] * (1 - weight)
    return merged


def _top_keywords(vec: Dict[str, float], top_n: int = 6) -> List[str]:
    return [t for t, _ in sorted(vec.items(), key=lambda kv: -kv[1])[:top_n]]


def _top_keywords_from_articles(articles: List[Dict], top_n: int = 6) -> List[str]:
    counter: Counter = Counter()
    for art in articles:
        counter.update(_article_tokens(art))
    return [t for t, _ in counter.most_common(top_n)]


def _label_for(keywords: List[str], articles: List[Dict]) -> str:
    haystack = " ".join(keywords + [a.get("title", "") for a in articles]).lower()
    # Word-boundary tokens from the haystack so short markers like "act" don't
    # accidentally match inside "react" or "fact".
    haystack_tokens = set(re.findall(r"[a-z0-9\-]+", haystack))

    best_label: str | None = None
    best_hits = 0
    for label, markers in _THEME_LABELS:
        hits = 0
        for marker in markers:
            if "-" in marker or len(marker) > 5:
                # Multi-word / long markers are specific enough for substring match.
                if marker in haystack:
                    hits += 1
            else:
                # Short markers must match a whole token to avoid false positives.
                if marker in haystack_tokens:
                    hits += 1
        if hits > best_hits:
            best_hits = hits
            best_label = label
    if best_label:
        return best_label
    # Fallback: capitalize the top keyword.
    if keywords:
        return keywords[0].capitalize()
    return "Signals"
