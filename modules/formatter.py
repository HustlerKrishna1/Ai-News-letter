"""Formatting layer: assemble final Markdown and optional HTML."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from config import settings

log = logging.getLogger(__name__)


def _sources_appendix(articles: List[Dict]) -> str:
    lines = ["## Sources", ""]
    for idx, art in enumerate(articles, start=1):
        title = art.get("title", "(untitled)").strip()
        src = art.get("source", "unknown")
        url = art.get("url", "")
        lines.append(f"{idx}. [{title}]({url}) — *{src}*")
    return "\n".join(lines)


def build_markdown(body: str, articles: List[Dict]) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    header = (
        f"# Signal Brief — {today}\n\n"
        "*AI · Economy · Capitalism · Power Shifts*\n\n"
        "---\n"
    )
    return f"{header}\n{body.strip()}\n\n---\n\n{_sources_appendix(articles)}\n"


_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _md_inline_to_html(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _INLINE_LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def markdown_to_html(markdown: str) -> str:
    """Minimal, dependency-free Markdown -> HTML converter sufficient for
    newsletter output (headings, paragraphs, lists, links, emphasis)."""
    lines = markdown.splitlines()
    out: List[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        if line.strip() == "---":
            close_list()
            out.append("<hr />")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_md_inline_to_html(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"  <li>{_md_inline_to_html(bullet.group(1))}</li>")
            continue

        numbered = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if numbered:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"  <li>{_md_inline_to_html(numbered.group(1))}</li>")
            continue

        close_list()
        out.append(f"<p>{_md_inline_to_html(line)}</p>")

    close_list()
    body = "\n".join(out)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        "<title>Signal Brief</title>\n"
        "<style>\n"
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:740px;"
        "margin:2rem auto;padding:0 1rem;line-height:1.55;color:#1a1a1a}\n"
        "h1{border-bottom:2px solid #333;padding-bottom:.3rem}\n"
        "h2{margin-top:2rem;color:#222}\n"
        "a{color:#0366d6;text-decoration:none}a:hover{text-decoration:underline}\n"
        "hr{border:none;border-top:1px solid #ddd;margin:1.5rem 0}\n"
        "em{color:#666}\n"
        "</style></head><body>\n"
        f"{body}\n"
        "</body></html>\n"
    )


def write_outputs(body: str, articles: List[Dict]) -> Tuple[Path, Path | None]:
    """Write Markdown (always) and HTML (optional). Returns the paths."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    md = build_markdown(body, articles)
    md_path = settings.output_dir / f"newsletter_{today}.md"
    md_path.write_text(md, encoding="utf-8")
    log.info("Wrote %s", md_path)

    html_path: Path | None = None
    if settings.emit_html:
        html_path = settings.output_dir / f"newsletter_{today}.html"
        html_path.write_text(markdown_to_html(md), encoding="utf-8")
        log.info("Wrote %s", html_path)

    return md_path, html_path
