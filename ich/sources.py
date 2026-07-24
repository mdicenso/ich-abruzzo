"""Serbatoio 2 — Flusso eventi & news, con connettori come plugin.

Fornisce il feed di contenuti candidati alla pipeline:
- un *seed* stabile e versionato (data/feed/events_seed.json), che include i casi
  di test del Guardrail;
- un'ingestione *live* da fonti reali elencate in data/feed/sources_config.json.

Dal Passo 5 le fonti sono **plugin** (come i canali di dispatch): ogni voce di
config ha un `kind` e il **registro connettori** (`CONNECTORS`) smista alla
funzione giusta. Aggiungere un tipo di fonte = registrare un connettore, senza
toccare `fetch_live`. Connettori inclusi: `rss` (RSS 2.0) e `json` (array
open-data, da URL o file locale, con mappatura campi configurabile).

Ogni item normalizzato porta `pubdate_iso` (data assoluta e stabile) oltre a
`detected` (tempo relativo per la UI): la data stabile alimenta l'id canonico
(hash fonte+data+titolo) → dedup reale anche per eventi omonimi in date diverse.

Nessuna dipendenza extra: `requests` (già portato da Streamlit) + stdlib.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data" / "feed"
SEED_PATH = _DATA / "events_seed.json"
CONFIG_PATH = _DATA / "sources_config.json"

_LIVE_ID_BASE = 1000  # gli id live partono da 1000, per non collidere col seed
_TAG_RE = re.compile(r"<[^>]+>")
_UA = {"User-Agent": "ICH-Abruzzo/1.0 (assistente turistico pubblico)"}


# ─── Sorgenti statiche / config ───────────────────────────────────────────────
def load_seed() -> list[dict]:
    """Item dimostrativi stabili + casi di test del Guardrail."""
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def load_config() -> list[dict]:
    """Fonti abilitate da ingerire. Delega a ich/feeds (backend durevole DB/JSON,
    gestibile dalla pagina 'Gestione dati'); fallback al file se qualcosa va storto."""
    try:
        from ich import feeds
        return feeds.list_enabled()
    except Exception:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return [feed for feed in json.load(f).get("feeds", []) if feed.get("enabled", True)]
        except Exception:
            return []


# ─── Helper comuni ────────────────────────────────────────────────────────────
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


def _parse_date(raw) -> datetime | None:
    """Parsa una data da formati comuni (ISO 8601, YYYY-MM-DD). None se non riesce."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt)
        except ValueError:
            continue
    return None


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


# ─── Connettori (uno per `kind`) ──────────────────────────────────────────────
def _connect_rss(feed: dict, max_items: int = 5) -> list[dict]:
    """Connettore RSS 2.0. Solleva in caso di rete/parse (gestito da fetch_live)."""
    resp = requests.get(feed["url"], headers=_UA, timeout=10)
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
            "pubdate_iso": _iso(dt),   # data stabile per l'id canonico
            "live": True,
            "url": link,
        })
    return out


def _connect_json(feed: dict, max_items: int = 5) -> list[dict]:
    """Connettore open-data: array JSON di eventi da URL o file locale (`path`,
    relativo alla root del progetto). `feed['map']` mappa i campi sorgente allo
    schema item: {title, description, link, date}."""
    if feed.get("path"):
        with open(_ROOT / feed["path"], encoding="utf-8") as f:
            data = json.load(f)
    else:
        resp = requests.get(feed["url"], headers=_UA, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    rows = data if isinstance(data, list) else data.get("items", data.get("events", []))

    fmap = feed.get("map", {})
    k_title = fmap.get("title", "title")
    k_desc = fmap.get("description", "description")
    k_link = fmap.get("link", "link")
    k_date = fmap.get("date", "date")

    out = []
    for i, row in enumerate(rows[:max_items]):
        title = str(row.get(k_title, "")).strip()
        if not title:
            continue
        dt = _parse_date(row.get(k_date, ""))
        out.append({
            "id": _LIVE_ID_BASE + i,
            "source": feed.get("source", feed.get("name", "Fonte open-data")),
            "icon": feed.get("icon", "🗂️"),
            "type": feed.get("type", "EVENTO"),
            "title": title,
            "raw": _clean(str(row.get(k_desc, "")) or title),
            # `date` dell'open-data è la data dell'EVENTO (spesso futura): giusta per
            # l'id canonico (pubdate_iso), non per il "quando rilevato" → neutro.
            "detected": "fonte live",
            "pubdate_iso": _iso(dt),
            "live": True,
            "url": str(row.get(k_link, feed.get("url", ""))),
        })
    return out


def _ics_unfold(text: str) -> list[str]:
    """Srotola le righe piegate (RFC 5545): una riga che inizia con spazio o TAB
    è la continuazione della precedente."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for ln in raw:
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    return lines


def _ics_unescape(v: str) -> str:
    """Riporta i caratteri escapati del formato TEXT iCal (\\n, \\, , \\; , \\\\)."""
    return (v.replace("\\n", " ").replace("\\N", " ")
             .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def _parse_ics_datetime(raw) -> datetime | None:
    """Parsa un valore DTSTART iCal: `YYYYMMDD`, `YYYYMMDDTHHMMSS`, con o senza `Z`.
    (Il TZID è già stato scartato: qui arriva solo il valore dopo i due punti.)"""
    if not raw:
        return None
    s = str(raw).strip()
    utc = s.endswith("Z")
    s = s.rstrip("Z")
    try:
        if "T" in s:
            dt = datetime.strptime(s, "%Y%m%dT%H%M%S")
        else:
            dt = datetime.strptime(s[:8], "%Y%m%d")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if utc else dt


def _connect_ical(feed: dict, max_items: int = 5) -> list[dict]:
    """Connettore iCalendar (.ics) — calendari pubblici di eventi (Google Calendar,
    comuni, pro loco). Legge i VEVENT da URL o file locale (`path`), estrae
    SUMMARY/DESCRIPTION/DTSTART/LOCATION/URL e li ordina per data (prossimi prima)."""
    if feed.get("path"):
        with open(_ROOT / feed["path"], encoding="utf-8") as f:
            text = f.read()
    else:
        resp = requests.get(feed["url"], headers=_UA, timeout=10)
        resp.raise_for_status()
        text = resp.text

    # 1) srotola e ricostruisci gli eventi (blocchi BEGIN:VEVENT … END:VEVENT)
    events: list[dict] = []
    cur: dict | None = None
    for line in _ics_unfold(text):
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT"):
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, value = line.split(":", 1)
            key = name.split(";", 1)[0].upper()  # scarta i parametri (TZID, VALUE…)
            if key in ("SUMMARY", "DESCRIPTION", "DTSTART", "LOCATION", "URL"):
                cur[key] = value

    # 2) ordina per DTSTART (senza data → in fondo). Normalizzo a naive per non
    # confrontare datetime aware (con `Z`) e naive (date-only/TZID) tra loro.
    def _key(ev):
        dt = _parse_ics_datetime(ev.get("DTSTART"))
        if dt is not None and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return (dt is None, dt or datetime.max)
    events.sort(key=_key)

    # 3) normalizza allo schema item comune
    out = []
    for i, ev in enumerate(events[:max_items]):
        title = _ics_unescape(ev.get("SUMMARY", ""))
        if not title:
            continue
        dt = _parse_ics_datetime(ev.get("DTSTART"))
        desc = _ics_unescape(ev.get("DESCRIPTION", ""))
        loc = _ics_unescape(ev.get("LOCATION", ""))
        body = (f"{desc} 📍 {loc}".strip() if loc else desc) or title
        out.append({
            "id": _LIVE_ID_BASE + i,
            "source": feed.get("source", feed.get("name", "Calendario eventi")),
            "icon": feed.get("icon", "📅"),
            "type": feed.get("type", "EVENTO"),
            "title": title,
            "raw": _clean(body),
            "source_kind": "ical",
            # DTSTART è la data dell'EVENTO (spesso futura): buona per l'id canonico
            # (pubdate_iso), non per il "quando rilevato" → neutro.
            "detected": "fonte live",
            "pubdate_iso": _iso(dt),
            "live": True,
            "url": _ics_unescape(ev.get("URL", "")) or feed.get("url", ""),
        })
    return out


# Registro connettori: kind → funzione. Aggiungere un tipo di fonte = una voce qui.
CONNECTORS = {
    "rss": _connect_rss,
    "json": _connect_json,
    "ical": _connect_ical,
}


def fetch_source(feed: dict, max_items: int = 5) -> list[dict]:
    """Smista una voce di config al connettore giusto in base al suo `kind`."""
    kind = feed.get("kind", "rss")
    connector = CONNECTORS.get(kind)
    if connector is None:
        raise ValueError(f"connettore sconosciuto per kind='{kind}'")
    return connector(feed, max_items)


def fetch_live(max_per_feed: int = 5) -> tuple[list[dict], list[str]]:
    """Ingerisce tutte le fonti abilitate via il connettore adatto. Ritorna
    (items, errori). Non solleva: ogni fonte che fallisce finisce in `errori` e
    viene saltata, così l'app resta sempre utilizzabile."""
    items: list[dict] = []
    errors: list[str] = []
    offset = 0
    for feed in load_config():
        try:
            batch = fetch_source(feed, max_items=max_per_feed)
            for it in batch:  # id univoci tra feed diversi
                it["id"] = _LIVE_ID_BASE + offset
                offset += 1
            items.extend(batch)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{feed.get('name', feed.get('url', '?'))}: {type(e).__name__}")
    return items, errors


def is_test_item(item: dict) -> bool:
    """True per i due item che pilotano il Guardrail con esito predefinito."""
    return item.get("id") in (4, 5)
