"""Formatting layer: assemble final Markdown and HTML via Jinja2 templates."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import settings

log = logging.getLogger(__name__)

_TEMPLATE_DIR = settings.project_root / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _sources_appendix(articles: List[Dict]) -> str:
    lines = ["## Sources", ""]
    for idx, art in enumerate(articles, start=1):
        title = art.get("title", "(untitled)").strip()
        src = art.get("source", "unknown")
        url = art.get("url", "")
        lines.append(f"{idx}. [{title}]({url}) — *{src}*")
    return "\n".join(lines)


def build_markdown(body: str, articles: List[Dict],
                   subject: Optional[str] = None,
                   meta: Optional[Dict] = None) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    title = subject or f"Signal Brief — {today}"
    meta = meta or {}
    cluster_line = ""
    if meta.get("clusters"):
        cluster_line = (
            "\n*Themes: "
            + " · ".join(f"{c['name']} ({c['count']})" for c in meta["clusters"])
            + "*\n"
        )
    header = (
        f"# {title}\n\n"
        "*AI · Economy · Capitalism · Power Shifts*\n"
        f"{cluster_line}"
        "\n---\n"
    )
    return f"{header}\n{body.strip()}\n\n---\n\n{_sources_appendix(articles)}\n"


# ---------- Minimal Markdown -> HTML (body only, for email template) ----------

_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _md_inline_to_html(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _INLINE_LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def _markdown_body_to_html(markdown: str) -> str:
    """Convert just the newsletter body (headings, paragraphs, lists, links).

    We strip the outer `# title` + `## Sources` appendix because the Jinja
    template provides them.
    """
    lines = markdown.splitlines()
    out: List[str] = []
    in_list = False
    in_sources = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("# "):
            continue  # title handled by template
        if stripped == "## Sources":
            in_sources = True
            continue
        if in_sources:
            continue
        if not stripped:
            close_list()
            continue
        if stripped == "---":
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_md_inline_to_html(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"  <li>{_md_inline_to_html(bullet.group(1))}</li>")
            continue

        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"  <li>{_md_inline_to_html(numbered.group(1))}</li>")
            continue

        close_list()
        out.append(f"<p>{_md_inline_to_html(stripped)}</p>")

    close_list()
    return "\n".join(out)


def render_email_html(markdown_doc: str, articles: List[Dict],
                      subject: str, meta: Optional[Dict] = None) -> str:
    meta = meta or {}
    body_html = _markdown_body_to_html(markdown_doc)
    return _env.get_template("email.html.j2").render(
        title=subject,
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        provider=meta.get("provider"),
        clusters=meta.get("clusters") or [],
        body_html=body_html,
        articles=articles,
        critique=meta.get("critique"),
    )


def markdown_to_html(markdown: str) -> str:
    """Back-compat helper: returns a standalone HTML document for the given
    markdown. Uses the email template with minimal metadata.

    New code should call `render_email_html` with structured args.
    """
    body_html = _markdown_body_to_html(markdown)
    title = _extract_title(markdown) or "Signal Brief"
    return _env.get_template("email.html.j2").render(
        title=title,
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        provider=None,
        clusters=[],
        body_html=body_html,
        articles=[],
        critique=None,
    )


def _extract_title(markdown: str) -> Optional[str]:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def write_outputs(body: str, articles: List[Dict],
                  subject: Optional[str] = None,
                  meta: Optional[Dict] = None) -> Tuple[Path, Path | None]:
    """Write Markdown (always) and HTML (optional). Returns the paths."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    md = build_markdown(body, articles, subject=subject, meta=meta)
    md_path = settings.output_dir / f"newsletter_{today}.md"
    md_path.write_text(md, encoding="utf-8")
    log.info("Wrote %s", md_path)

    html_path: Path | None = None
    if settings.emit_html:
        title = subject or f"Signal Brief — {today}"
        html_out = render_email_html(md, articles, title, meta=meta)
        html_path = settings.output_dir / f"newsletter_{today}.html"
        html_path.write_text(html_out, encoding="utf-8")
        log.info("Wrote %s", html_path)

    return md_path, html_path
