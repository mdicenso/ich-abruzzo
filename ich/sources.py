"""Serbatoio 2 — Flusso eventi & news.

Fornisce il feed di contenuti candidati alla pipeline:
- un *seed* stabile e versionato (data/feed/events_seed.json), che include i casi
  di test del Guardrail;
- un'ingestione *live* da fonti RSS reali (data/feed/sources_config.json),
  normalizzate nello stesso schema degli item del seed.

Nessuna dipendenza extra: usa `requests` (già portato da Streamlit) e la
libreria standard. La cache (TTL) è gestita dal chiamante (app.py).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

_DATA = Path(__file__).resolve().parent.parent / "data" / "feed"
SEED_PATH = _DATA / "events_seed.json"
CONFIG_PATH = _DATA / "sources_config.json"

_LIVE_ID_BASE = 1000  # gli id live partono da 1000, per non collidere col seed
_TAG_RE = re.compile(r"<[^>]+>")


def load_seed() -> list[dict]:
    """Item dimostrativi stabili + casi di test del Guardrail."""
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def load_config() -> list[dict]:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return [feed for feed in json.load(f).get("feeds", []) if feed.get("enabled", True)]
    except Exception:
        return []


def _relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "fonte live"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (now - dt).total_seconds()
    if secs < 90:
        return "adesso"
    if secs < 3600:
        return f"{int(secs // 60)} min fa"
    if secs < 86400:
        return f"{int(secs // 3600)}h fa"
    return f"{int(secs // 86400)}g fa"


def _clean(text: str, limit: int = 400) -> str:
    text = _TAG_RE.sub("", text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def fetch_rss(feed: dict, max_items: int = 5) -> list[dict]:
    """Scarica e normalizza un feed RSS 2.0. Solleva eccezione in caso di rete/parse."""
    headers = {"User-Agent": "ICH-Abruzzo/1.0 (assistente turistico pubblico)"}
    resp = requests.get(feed["url"], headers=headers, timeout=10)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = root.findall(".//item")[:max_items]
    out = []
    for i, it in enumerate(items):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        desc = _clean(it.findtext("description") or "")
        link = (it.findtext("link") or "").strip()
        raw_pub = it.findtext("pubDate")
        try:
            dt = parsedate_to_datetime(raw_pub) if raw_pub else None
        except Exception:
            dt = None
        out.append({
            "id": _LIVE_ID_BASE + i,
            "source": feed.get("source", feed.get("name", "Fonte live")),
            "icon": feed.get("icon", "📰"),
            "type": feed.get("type", "NEWS"),
            "title": title,
            "raw": desc or title,
            "detected": _relative_time(dt),
            "live": True,
            "url": link,
        })
    return out


def fetch_live(max_per_feed: int = 5) -> tuple[list[dict], list[str]]:
    """Ingerisce tutte le fonti abilitate. Ritorna (items, errori).

    Non solleva: ogni feed che fallisce finisce in `errori` e viene saltato,
    così l'app resta sempre utilizzabile.
    """
    items: list[dict] = []
    errors: list[str] = []
    offset = 0
    for feed in load_config():
        try:
            batch = fetch_rss(feed, max_items=max_per_feed)
            for it in batch:  # riassegna id univoci tra feed diversi
                it["id"] = _LIVE_ID_BASE + offset
                offset += 1
            items.extend(batch)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{feed.get('name', feed.get('url','?'))}: {type(e).__name__}")
    return items, errors


def is_test_item(item: dict) -> bool:
    """True per i due item che pilotano il Guardrail con esito predefinito."""
    return item.get("id") in (4, 5)
