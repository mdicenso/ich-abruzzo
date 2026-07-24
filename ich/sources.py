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
import os
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
def _localname(tag: str) -> str:
    """Nome locale di un tag XML, senza namespace ({ns}tag → tag)."""
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el, names: tuple) -> str:
    """Testo del primo figlio diretto il cui nome locale è tra `names`."""
    for ch in el:
        if _localname(ch.tag) in names and (ch.text or "").strip():
            return ch.text.strip()
    return ""


def _entry_link(el) -> str:
    """Link di un item/entry: testo di <link> (RSS) oppure href di <link> (Atom,
    preferendo rel='alternate' o assente)."""
    fallback = ""
    for ch in el:
        if _localname(ch.tag) != "link":
            continue
        href = (ch.get("href") or "").strip()          # Atom: href in attributo
        if href:
            if (ch.get("rel") or "alternate").lower() == "alternate":
                return href
            fallback = fallback or href
        elif (ch.text or "").strip():                    # RSS: link come testo
            return ch.text.strip()
    return fallback


def _parse_feed_date(raw):
    """Data di un feed: prova RFC 822 (RSS pubDate) poi ISO 8601 (Atom)."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return _parse_date(raw)


def _connect_feed(feed: dict, max_items: int = 5) -> list[dict]:
    """Connettore di sindacazione UNIFICATO: riconosce da solo **RSS (2.0/1.0)**
    e **Atom** e li normalizza allo stesso schema — un unico `kind` per tutti i
    feed. Legge da URL o da file locale (`path`). Solleva su rete/parse (gestito
    da fetch_live). Il formato è dedotto dalla radice (`<feed>` = Atom, altrimenti
    RSS/RDF); i namespace XML sono gestiti per nome locale."""
    if feed.get("path"):
        with open(_ROOT / feed["path"], "rb") as f:
            content = f.read()
    else:
        resp = requests.get(feed["url"], headers=_UA, timeout=10)
        resp.raise_for_status()
        content = resp.content
    root = ET.fromstring(content)

    is_atom = _localname(root.tag) == "feed"
    entry_name = "entry" if is_atom else "item"
    entries = [el for el in root.iter() if _localname(el.tag) == entry_name][:max_items]

    out = []
    for i, it in enumerate(entries):
        title = _child_text(it, ("title",))
        if not title:
            continue
        body = _child_text(it, ("description", "summary", "content", "subtitle"))
        raw_date = _child_text(it, ("pubdate", "published", "updated", "date"))
        dt = _parse_feed_date(raw_date)
        out.append({
            "id": _LIVE_ID_BASE + i,
            "source": feed.get("source", feed.get("name", "Fonte live")),
            "icon": feed.get("icon", "📰"),
            "type": feed.get("type", "NEWS"),
            "title": title,
            "raw": _clean(body) or title,
            "source_kind": "atom" if is_atom else "rss",
            "detected": _relative_time(dt),
            "pubdate_iso": _iso(dt),   # data stabile per l'id canonico
            "live": True,
            "url": _entry_link(it),
        })
    return out


_SECRET_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_secret(value):
    """Sostituisce i placeholder `${VAR}` con il valore da os.environ o
    st.secrets. Serve a NON salvare token/API-key in chiaro nella config: nel
    feed si scrive es. "Bearer ${EVENTS_API_TOKEN}" e il segreto vive nei secret."""
    if not isinstance(value, str) or "${" not in value:
        return value

    def repl(m):
        name = m.group(1)
        v = os.environ.get(name)
        if v:
            return v
        try:
            import streamlit as st
            return str(st.secrets.get(name, "")) or ""
        except Exception:
            return ""
    return _SECRET_RE.sub(repl, value)


def _get_by_path(obj, dotted: str):
    """Naviga un percorso puntato (es. 'data.results' o '_embedded.events') dentro
    la risposta JSON. Ritorna None se il percorso non esiste."""
    cur = obj
    for part in (dotted or "").split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _extract_rows(data, feed: dict) -> list:
    """Estrae l'array di record dalla risposta: `data_path` se indicato, altrimenti
    euristica (lista diretta, o chiavi items/events/results)."""
    dp = feed.get("data_path")
    if dp:
        got = _get_by_path(data, dp)
        return got if isinstance(got, list) else []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items", data.get("events", data.get("results", []))) or []
    return []


def _fetch_rest_rows(feed: dict, max_items: int) -> list:
    """Scarica i record da un endpoint (GET), con header/params opzionali (valori
    con `${VAR}` risolti dai secret) e paginazione opzionale e **limitata**:
    - {"type":"page","param":"page","start":1,"max_pages":N}
    - {"type":"next","next_path":"_links.next.href","max_pages":N}
    Senza `paginate` fa una sola richiesta (comportamento storico)."""
    headers = dict(_UA)
    for k, v in (feed.get("headers") or {}).items():
        headers[k] = _resolve_secret(v)
    params = {k: _resolve_secret(v) for k, v in (feed.get("params") or {}).items()}

    pag = feed.get("paginate") or {}
    max_pages = max(1, int(pag.get("max_pages", 1)))
    url = feed["url"]
    page = int(pag.get("start", 1))
    rows: list = []
    for _ in range(max_pages):
        p = dict(params)
        if pag.get("type") == "page":
            p[pag.get("param", "page")] = page
        resp = requests.get(url, headers=headers, params=p, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        batch = _extract_rows(data, feed)
        rows.extend(batch)
        if len(rows) >= max_items or not batch:
            break
        if pag.get("type") == "next":
            nxt = _get_by_path(data, pag.get("next_path", "next"))
            if not nxt:
                break
            url, params = nxt, {}  # la next URL è già completa
        elif pag.get("type") == "page":
            page += 1
        else:
            break  # nessuna paginazione → una sola richiesta
    return rows


def _connect_json(feed: dict, max_items: int = 5) -> list[dict]:
    """Connettore dati JSON / **API REST**. Sorgente:
    - file locale `path` (array o oggetto), oppure
    - endpoint `url` (GET) con `headers`/`params` opzionali (valori `${VAR}` dai
      secret), `data_path` (percorso all'array nella risposta) e `paginate`.
    `feed['map']` rimappa i campi sorgente allo schema item {title, description,
    link, date}."""
    if feed.get("path"):
        with open(_ROOT / feed["path"], encoding="utf-8") as f:
            data = json.load(f)
        rows = _extract_rows(data, feed)
    else:
        rows = _fetch_rest_rows(feed, max_items)

    fmap = feed.get("map", {})
    k_title = fmap.get("title", "title")
    k_desc = fmap.get("description", "description")
    k_link = fmap.get("link", "link")
    k_date = fmap.get("date", "date")

    out = []
    for i, row in enumerate(rows[:max_items]):
        if not isinstance(row, dict):
            continue
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
            "source_kind": feed.get("kind", "json"),
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
# rss/atom/feed puntano allo stesso connettore unificato (auto-detect RSS vs Atom).
CONNECTORS = {
    "rss": _connect_feed,
    "atom": _connect_feed,
    "feed": _connect_feed,
    "json": _connect_json,
    "rest": _connect_json,
    "api": _connect_json,
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
