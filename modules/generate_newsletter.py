"""AI generation layer.

Takes the processed article list and produces a full newsletter body using a
pluggable LLM backend (Anthropic, OpenAI, or a deterministic "mock" generator
for offline runs / tests).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Protocol

from config import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite macro + AI analyst.

Generate a high-signal newsletter with these sections (in order):
1. Reality Check
2. Key Developments
3. Pattern Recognition
4. Opportunity Layer
5. Strategic Advice
6. Bold Prediction

Focus on: AI + economy + capitalism + power shifts.
Avoid fluff. Prioritize insight and second-order thinking.
Write in clean Markdown. Use H2 headings for each section.
"""


def _articles_to_context(articles: List[Dict]) -> str:
    lines = []
    for idx, art in enumerate(articles, start=1):
        lines.append(
            f"[{idx}] {art.get('title', '')} — {art.get('source', 'unknown')}\n"
            f"    URL: {art.get('url', '')}\n"
            f"    Summary: {art.get('summary', '')[:500]}"
        )
    return "\n\n".join(lines)


def _build_user_prompt(articles: List[Dict]) -> str:
    today = datetime.utcnow().strftime("%B %d, %Y")
    context = _articles_to_context(articles)
    return (
        f"Today is {today}.\n\n"
        f"Here are {len(articles)} ranked news items from the last ~48 hours:\n\n"
        f"{context}\n\n"
        "Using ONLY these inputs (plus broadly known macro context), draft the newsletter. "
        "Cite specific developments where relevant. Keep it under ~1200 words."
    )


class LLMClient(Protocol):
    def generate(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        import anthropic  # type: ignore
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def generate(self, system: str, user: str) -> str:
        resp = self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()


class OpenAIClient:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import OpenAI  # type: ignore
        self._client = OpenAI(api_key=settings.openai_api_key)

    def generate(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=settings.llm_max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()


class MockClient:
    """Deterministic offline generator. Produces a valid newsletter body
    derived from the top articles — useful for tests and key-less runs."""

    def generate(self, system: str, user: str) -> str:
        # Extract the top N bullets from the injected context (lines starting with "[n] ").
        lines = [ln for ln in user.splitlines() if ln.startswith("[")]
        top = lines[:10]
        bullets = "\n".join(f"- {ln}" for ln in top) or "- No articles available."
        return (
            "## Reality Check\n"
            "The macro tape is telling a consistent story: compute capex is swallowing free "
            "cash flow, rate expectations are re-pricing in real time, and platform incumbents "
            "are consolidating leverage over smaller labs and nation-state buyers. Look past "
            "the headline count — concentration is the signal.\n\n"
            "## Key Developments\n"
            f"{bullets}\n\n"
            "## Pattern Recognition\n"
            "Three threads braid together: (1) AI capex is now a macro variable, not a tech one; "
            "(2) policy responses are fragmenting along geopolitical lines; (3) distribution — "
            "not model quality — is emerging as the durable moat.\n\n"
            "## Opportunity Layer\n"
            "- Picks-and-shovels exposure (power, cooling, interconnect) remains underpriced "
            "relative to inference demand curves.\n"
            "- Vertical AI wrappers with proprietary workflow data > horizontal chat UIs.\n"
            "- Regulatory arbitrage windows in mid-size jurisdictions are still open.\n\n"
            "## Strategic Advice\n"
            "Treat AI not as a product category but as a cost-structure shift. Re-underwrite "
            "every recurring-revenue business on the assumption that 30–50% of knowledge-work "
            "unit costs are compressible within 36 months. Act before your competitors do.\n\n"
            "## Bold Prediction\n"
            "Within 18 months, at least one G7 economy will tie sovereign debt issuance to "
            "AI-driven productivity targets — the first explicit fusion of fiscal policy and "
            "model-compute planning.\n"
        )


def _pick_client() -> LLMClient:
    provider = settings.llm_provider
    try:
        if provider == "anthropic":
            return AnthropicClient()
        if provider == "openai":
            return OpenAIClient()
    except Exception as exc:  # noqa: BLE001 - fallback intentionally broad
        log.warning("LLM provider '%s' unavailable (%s). Falling back to mock.", provider, exc)
    if provider not in {"mock", "anthropic", "openai"}:
        log.warning("Unknown LLM_PROVIDER='%s'. Using mock.", provider)
    return MockClient()


def generate_newsletter(articles: List[Dict]) -> str:
    """Build a newsletter body (Markdown) from ranked articles."""
    if not articles:
        return "## Reality Check\nNo articles were available to analyze today."
    client = _pick_client()
    user_prompt = _build_user_prompt(articles)
    log.info("Generating newsletter via %s", client.__class__.__name__)
    return client.generate(SYSTEM_PROMPT, user_prompt)
