"""Multi-channel delivery router.

Dispatches a freshly-generated issue to any combination of:
  * email    — SMTP or SendGrid (delegated to modules.email_sender)
  * slack    — Incoming Webhook URL
  * discord  — Incoming Webhook URL (same JSON shape as Slack for text)
  * telegram — Bot API (token + chat ID)
  * rss      — write / update output/rss.xml (the newsletter as a subscribable feed)

Each channel is independent: one failure does not block the others. The
returned summary tells the caller which channels went through.
"""
from __future__ import annotations

import html
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

from config import settings
from modules.email_sender import EmailError, send_newsletter

log = logging.getLogger(__name__)


# ---------- Slack / Discord ----------

def _slack_blocks(subject: str, body_md: str, issue_url: str | None) -> List[Dict]:
    """Slack Block Kit representation. Trims body to Slack's length limits."""
    preview = body_md.strip().split("\n\n", 1)[0][:900]
    blocks: List[Dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": subject[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": preview}},
    ]
    if issue_url:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{issue_url}|Read the full brief →>"},
        })
    return blocks


def send_slack(subject: str, body_md: str, issue_url: str | None = None) -> None:
    if not settings.slack_webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL not set")
    payload = {"text": subject, "blocks": _slack_blocks(subject, body_md, issue_url)}
    resp = requests.post(settings.slack_webhook_url, json=payload,
                         timeout=settings.http_timeout)
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack webhook rejected: {resp.status_code} {resp.text}")
    log.info("Slack delivery OK")


def send_discord(subject: str, body_md: str, issue_url: str | None = None) -> None:
    if not settings.discord_webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")
    preview = body_md.strip().split("\n\n", 1)[0]
    content = f"**{subject}**\n\n{preview[:1700]}"
    if issue_url:
        content += f"\n\n[Read the full brief]({issue_url})"
    resp = requests.post(
        settings.discord_webhook_url,
        json={"content": content[:1999]},
        timeout=settings.http_timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord webhook rejected: {resp.status_code} {resp.text}")
    log.info("Discord delivery OK")


# ---------- Telegram ----------

def send_telegram(subject: str, body_md: str, issue_url: str | None = None) -> None:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    preview = body_md.strip().split("\n\n", 1)[0]
    text = f"*{_tg_escape(subject)}*\n\n{_tg_escape(preview[:3500])}"
    if issue_url:
        text += f"\n\n[Read the full brief]({issue_url})"

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        },
        timeout=settings.http_timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Telegram rejected: {resp.status_code} {resp.text}")
    log.info("Telegram delivery OK")


def _tg_escape(text: str) -> str:
    """Escape MarkdownV2 special characters per Telegram's rules."""
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join("\\" + c if c in specials else c for c in text)


# ---------- RSS feed output ----------

def update_rss_feed(issues: Iterable[Dict], feed_path: Optional[Path] = None) -> Path:
    """Write/overwrite an RSS 2.0 feed containing the most recent issues.

    Each `issue` dict needs: issue_date, subject, markdown_path, html_path.
    URLs in <link> are inferred from PUBLIC_BASE_URL (for hosted dashboards);
    if unset, they point at the on-disk HTML path.
    """
    feed_path = feed_path or (settings.output_dir / "rss.xml")
    base = (settings.public_base_url or "").rstrip("/")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Signal Brief — AI, Economy, Power"
    ET.SubElement(channel, "description").text = (
        "Daily AI-generated brief on AI, economy, capitalism, and power shifts."
    )
    ET.SubElement(channel, "link").text = base or "https://github.com/HustlerKrishna1/Ai-News-letter"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(channel, "generator").text = "newsletter-ai/3.0"

    for issue in issues:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            issue.get("subject") or f"Signal Brief {issue['issue_date']}"
        )
        link = (
            f"{base}/issue/{issue['issue_date']}"
            if base else f"file://{issue.get('html_path') or issue.get('markdown_path')}"
        )
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = issue["issue_date"]
        try:
            dt = datetime.fromisoformat(issue["issue_date"] + "T12:00:00+00:00")
            ET.SubElement(item, "pubDate").text = format_datetime(dt)
        except ValueError:
            pass
        # Short description — first paragraph of the markdown.
        desc = _issue_description(issue)
        if desc:
            ET.SubElement(item, "description").text = desc

    ET.ElementTree(rss).write(feed_path, encoding="utf-8", xml_declaration=True)
    log.info("RSS feed written to %s", feed_path)
    return feed_path


def _issue_description(issue: Dict) -> str:
    md_path = issue.get("markdown_path")
    if not md_path:
        return ""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    # Skip the title line and any metadata; take the first real paragraph.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        if not para.startswith("#") and "---" not in para and "*AI ·" not in para:
            return html.escape(para[:600])
    return ""


# ---------- Router ----------

def deliver(subject: str, body_md: str, body_html: str, issue_date: str,
            channels: List[str], issue_url: str | None = None,
            email_recipients: Iterable[str] | None = None) -> Dict[str, str]:
    """Attempt each requested channel; return {channel: "ok"|"error: ..."}."""
    results: Dict[str, str] = {}
    for channel in channels:
        channel = channel.strip().lower()
        if not channel:
            continue
        try:
            if channel == "email":
                send_newsletter(body_md, body_html, issue_date,
                                recipients=list(email_recipients) if email_recipients else None)
            elif channel == "slack":
                send_slack(subject, body_md, issue_url)
            elif channel == "discord":
                send_discord(subject, body_md, issue_url)
            elif channel == "telegram":
                send_telegram(subject, body_md, issue_url)
            else:
                results[channel] = f"error: unknown channel"
                continue
            results[channel] = "ok"
        except (EmailError, RuntimeError, requests.RequestException) as exc:
            log.error("Delivery to %s failed: %s", channel, exc)
            results[channel] = f"error: {exc}"
    return results
