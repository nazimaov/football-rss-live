#!/usr/bin/env python3
"""Refresh the six RSS mirrors used by the football Telegram bot."""

import html
import json
import logging
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import feedparser
import requests

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("rss-update")

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "sources_state.json"
USER_AGENT = "football-news-rss-updater/1.0 (+https://github.com/nazimaov3-blip/rss)"
TIMEOUT = 30
MAX_ITEMS = 60


def clean_text(value: str) -> str:
    return " ".join(html.unescape(value or "").split())


def parse_date(entry):
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def build_xml(source, entries):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = source["name"]
    ET.SubElement(channel, "link").text = source["site"]
    ET.SubElement(channel, "description").text = f"RSS feed for {source['name']}"
    ET.SubElement(channel, "language").text = "ru-RU"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(channel, "generator").text = "Football RSS Mirror"

    for entry in entries[:MAX_ITEMS]:
        title = clean_text(entry.get("title", ""))
        link = clean_text(entry.get("link", ""))
        if not title or not link:
            continue
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = clean_text(
            entry.get("id") or entry.get("guid") or link
        )
        summary = entry.get("summary") or entry.get("description") or ""
        ET.SubElement(item, "description").text = clean_text(summary)
        published = parse_date(entry)
        if published:
            ET.SubElement(item, "pubDate").text = format_datetime(published)
        source_tag = entry.get("source", {})
        if isinstance(source_tag, dict) and source_tag.get("title"):
            ET.SubElement(item, "category").text = clean_text(source_tag["title"])

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="unicode", xml_declaration=True) + "\n"


def item_signature(xml_text: str):
    try:
        root = ET.fromstring(xml_text)
        return tuple(
            (item.findtext("guid", ""), item.findtext("link", ""), item.findtext("title", ""))
            for item in root.findall("./channel/item")
        )
    except Exception:
        return None


def refresh_source(source):
    logger.info("Обновляю %s", source["name"])
    response = requests.get(
        source["url"],
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if not feed.entries:
        raise RuntimeError("RSS не содержит записей")

    new_xml = build_xml(source, feed.entries)
    target = ROOT / source["file"]
    old_xml = target.read_text(encoding="utf-8") if target.exists() else ""
    if item_signature(old_xml) == item_signature(new_xml):
        logger.info("  без изменений (%d записей)", len(feed.entries))
        return False

    target.write_text(new_xml, encoding="utf-8")
    logger.info("  обновлено: %s (%d записей)", target.name, len(feed.entries))
    return True


def main():
    sources = json.loads(STATE_FILE.read_text(encoding="utf-8"))["sources"]
    changed = 0
    errors = 0
    for source in sources:
        try:
            changed += int(refresh_source(source))
        except Exception as exc:
            errors += 1
            logger.error("  ошибка %s: %s", source["name"], exc)
    logger.info("Итог: изменено=%d ошибок=%d", changed, errors)
    return 1 if errors == len(sources) else 0


if __name__ == "__main__":
    sys.exit(main())
