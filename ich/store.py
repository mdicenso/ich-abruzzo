"""Persistenza del motore ICH — backend selezionabile (JSON locale o Postgres).

Due backend, stessa identica interfaccia pubblica (il resto di ICH non cambia):

- **JSON locale** (default): file versionati sotto data/store e data/published.
  Ottimo per lo sviluppo offline sul PC; nessuna dipendenza extra.
- **Postgres / Neon** (se è impostato `ICH_DATABASE_URL`): stato durevole che
  sopravvive ai redeploy del cloud (il disco di Streamlit Cloud è effimero).
  Attivato solo quando la connection string è presente (env o `st.secrets`).

La scelta è automatica: c'è la stringa → Postgres; non c'è → JSON. Se il DB non
è raggiungibile si **degrada al JSON** senza mai sollevare, così l'app resta viva
(stessa filosofia delle letture tolleranti di prima).

`export_to_json()` è la **via d'espianto**: rigenera i file JSON locali dal backend
attivo, così i dati sono sempre estraibili (per backup o reingegnerizzazione).

Scritture JSON atomiche (tmp + os.replace) per non lasciare file mezzo-scritti.
`_atomic_write` resta pubblico: lo usa anche ich/topics.py.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = _ROOT / "data" / "store"
PUBLISHED_DIR = _ROOT / "data" / "published"
ITEMS_PATH = STORE_DIR / "items.json"
FEED_PATH = PUBLISHED_DIR / "feed.json"
AUDIT_PATH = STORE_DIR / "audit.jsonl"
QUERIES_PATH = STORE_DIR / "queries.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dirs() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str) -> None:
    """Scrittura atomica (tmp + os.replace). Su cartelle sincronizzate da OneDrive
    o toccate dall'antivirus `os.replace` può fallire con WinError 5 perché il file
    è bloccato per un istante: si riprova qualche volta e, come ultima spiaggia, si
    scrive direttamente (perdendo l'atomicità ma non i dati). In cloud (disco non
    OneDrive) il primo tentativo va sempre a segno."""
    _ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for attempt in range(4):
        try:
            os.replace(tmp, path)  # atomico sullo stesso filesystem
            return
        except PermissionError:
            if attempt < 3:
                time.sleep(0.15 * (attempt + 1))
    # fallback: scrittura diretta se il lock persiste
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SELEZIONE DEL BACKEND
# ═══════════════════════════════════════════════════════════════════════════
def _database_url() -> str:
    """Connection string Postgres, se configurata. Ordine: variabile d'ambiente
    `ICH_DATABASE_URL` → `st.secrets["ICH_DATABASE_URL"]`. Vuota → backend JSON."""
    url = (os.environ.get("ICH_DATABASE_URL", "") or "").strip()
    if url:
        return url
    try:  # streamlit è opzionale qui (gli smoke test girano senza)
        import streamlit as st
        return (st.secrets.get("ICH_DATABASE_URL", "") or "").strip()
    except Exception:
        return ""


_PG = None  # istanza PgStore, costruita e cachata al primo uso riuscito


def _backend():
    """Ritorna il backend Postgres attivo, o None (→ JSON). Non solleva mai:
    se il DB non è configurato o non è raggiungibile ritorna None e l'app usa i
    file JSON. Il successo viene cachato; un fallimento non viene cachato, così
    un problema transitorio di rete viene riprovato al giro dopo."""
    global _PG
    if _PG is not None:
        return _PG
    url = _database_url()
    if not url:
        return None
    try:
        from ich import store_pg
        pg = store_pg.PgStore(url)
        pg.ensure_schema()
        _PG = pg
        return _PG
    except Exception:
        return None


def backend_name() -> str:
    """Etichetta leggibile del backend attivo (per la UI 'Gestione dati')."""
    return "Postgres (Neon)" if _backend() is not None else "JSON locale"


# ═══════════════════════════════════════════════════════════════════════════
# ITEMS NORMALIZZATI  (ledger dei CanonicalItem)
# ═══════════════════════════════════════════════════════════════════════════
def _json_load_items() -> list[dict]:
    try:
        with open(ITEMS_PATH, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def _json_save_items(items: list[dict]) -> None:
    payload = {"updated_at": _now_iso(), "count": len(items), "items": items}
    _atomic_write(ITEMS_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def load_items() -> list[dict]:
    pg = _backend()
    if pg is not None:
        try:
            return pg.load_items()
        except Exception:
            pass
    return _json_load_items()


def save_items(items: list[dict]) -> None:
    pg = _backend()
    if pg is not None:
        try:
            pg.save_items(items)
            return
        except Exception:
            pass
    _json_save_items(items)


def upsert_item(item: dict) -> list[dict]:
    """Inserisce o aggiorna un item per `id` (dedup), preservando l'ordine.
    Ritorna la lista completa aggiornata."""
    pg = _backend()
    if pg is not None:
        try:
            pg.upsert_item(item)
            return pg.load_items()
        except Exception:
            pass
    items = _json_load_items()
    iid = item.get("id")
    for i, existing in enumerate(items):
        if existing.get("id") == iid:
            items[i] = item
            break
    else:
        items.append(item)
    _json_save_items(items)
    return items


def get_item(item_id: str) -> dict | None:
    pg = _backend()
    if pg is not None:
        try:
            return pg.get_item(item_id)
        except Exception:
            pass
    for it in _json_load_items():
        if it.get("id") == item_id:
            return it
    return None


# ═══════════════════════════════════════════════════════════════════════════
# OUTBOX DEI CANALI  (uscite del dispatch)
# ═══════════════════════════════════════════════════════════════════════════
# Ogni canale scrive il suo outbox durevole. Il canale API usa il nome storico
# "feed" (feed.json), stabile per i consumatori esterni (es. Abruzzo Wild).
def _outbox_path(channel: str) -> Path:
    return PUBLISHED_DIR / f"{channel}.json"


def _json_load_outbox(channel: str) -> list[dict]:
    try:
        with open(_outbox_path(channel), encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def _json_save_outbox(channel: str, entries: list[dict]) -> None:
    payload = {"channel": channel, "updated_at": _now_iso(),
               "count": len(entries), "items": entries}
    _atomic_write(_outbox_path(channel), json.dumps(payload, ensure_ascii=False, indent=2))


def load_outbox(channel: str) -> list[dict]:
    pg = _backend()
    if pg is not None:
        try:
            return pg.load_outbox(channel)
        except Exception:
            pass
    return _json_load_outbox(channel)


def save_outbox(channel: str, entries: list[dict]) -> None:
    pg = _backend()
    if pg is not None:
        try:
            pg.save_outbox(channel, entries)
            return
        except Exception:
            pass
    _json_save_outbox(channel, entries)


# Alias di compatibilità: il "feed" è l'outbox del canale API.
def load_feed() -> list[dict]:
    return load_outbox("feed")


def save_feed(entries: list[dict]) -> None:
    save_outbox("feed", entries)


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT LOG  (EU AI Act) — append-only
# ═══════════════════════════════════════════════════════════════════════════
def _json_append_audit(entry: dict) -> None:
    _ensure_dirs()
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _json_load_audit(limit: int | None = None) -> list[dict]:
    try:
        with open(AUDIT_PATH, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []
    rows.reverse()
    return rows[:limit] if limit else rows


def append_audit(event: str, item_id: str, source: str, detail: str,
                 actor: str = "system", title: str = "") -> dict:
    """Aggiunge una riga al log append-only. `actor`: 'system' | 'operator'."""
    entry = {"ts": _now_iso(), "event": event, "item_id": item_id, "title": title,
             "source": source, "actor": actor, "detail": detail}
    pg = _backend()
    if pg is not None:
        try:
            pg.append_audit(entry)
            return entry
        except Exception:
            pass
    _json_append_audit(entry)
    return entry


def load_audit(limit: int | None = None) -> list[dict]:
    """Ritorna le righe del log, più recenti prima."""
    pg = _backend()
    if pg is not None:
        try:
            return pg.load_audit(limit)
        except Exception:
            pass
    return _json_load_audit(limit)


# ═══════════════════════════════════════════════════════════════════════════
# DOMANDA DUREVOLE  (query reali all'assistente → segnale per l'Intelligence C)
# ═══════════════════════════════════════════════════════════════════════════
def _json_append_query(entry: dict) -> None:
    _ensure_dirs()
    with open(QUERIES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _json_load_queries() -> list[dict]:
    try:
        with open(QUERIES_PATH, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []


def append_query(q: str, answered: bool, categories: list) -> dict:
    """Registra una query reale posta all'assistente."""
    entry = {"ts": _now_iso(), "q": q, "answered": bool(answered),
             "categories": categories or []}
    pg = _backend()
    if pg is not None:
        try:
            pg.append_query(entry)
            return entry
        except Exception:
            pass
    _json_append_query(entry)
    return entry


def load_queries() -> list[dict]:
    pg = _backend()
    if pg is not None:
        try:
            return pg.load_queries()
        except Exception:
            pass
    return _json_load_queries()


# ═══════════════════════════════════════════════════════════════════════════
# ESPIANTO — rigenera i file JSON locali dal backend attivo
# ═══════════════════════════════════════════════════════════════════════════
def export_to_json() -> dict:
    """Scrive lo stato del backend attivo nei file JSON locali (backup/espianto).
    Ritorna un conteggio per categoria. Utile per portare via i dati da Neon
    senza toccare il DB, o per un backup versionabile nel repo."""
    items = load_items()
    _json_save_items(items)

    channels_done = {}
    for ch in ("feed", "chatbot", "mobile", "signage", "tv"):
        entries = load_outbox(ch)
        _json_save_outbox(ch, entries)
        channels_done[ch] = len(entries)

    # audit e queries: riscrivo i .jsonl da zero dal backend
    _ensure_dirs()
    audit = list(reversed(load_audit()))  # load_audit dà recenti-prima; il file è cronologico
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        for e in audit:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    queries = load_queries()
    with open(QUERIES_PATH, "w", encoding="utf-8") as f:
        for e in queries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # argomenti editoriali (import ritardato: topics importa store, non il contrario)
    n_topics = 0
    try:
        from ich import topics as _topics
        topics_list = _topics.load_topics()
        _topics._json_save_topics(topics_list)
        n_topics = len(topics_list)
    except Exception:
        pass

    return {"items": len(items), "outbox": channels_done,
            "audit": len(audit), "queries": len(queries), "topics": n_topics}


def import_from_json(force: bool = False) -> dict:
    """Carica i file JSON locali DENTRO il backend attivo (migrazione JSON→DB).
    Ha senso solo con un backend Postgres: serve a portare su Neon lo stato già
    esistente in locale (es. la prima volta), senza perdere nulla. In modalità
    JSON è un no-op (ri-scrivere gli stessi file duplicherebbe audit/queries).

    Idempotenza: se il DB ha già item/audit/query si **salta** (per non duplicare
    i log append-only), a meno di `force=True`."""
    pg = _backend()
    if pg is None:
        return {"skipped": "nessun backend DB attivo"}
    if not force and (pg.load_items() or pg.load_audit(1) or pg.load_queries()):
        return {"skipped": "il DB è già popolato (usa force=True per forzare)"}

    items = _json_load_items()
    for it in items:
        pg.upsert_item(it)

    channels_done = {}
    for ch in ("feed", "chatbot", "mobile", "signage", "tv"):
        entries = _json_load_outbox(ch)
        if entries:
            pg.save_outbox(ch, entries)
            channels_done[ch] = len(entries)

    audit = list(reversed(_json_load_audit()))  # cronologico (il file lo è)
    for e in audit:
        pg.append_audit(e)
    queries = _json_load_queries()
    for e in queries:
        pg.append_query(e)

    return {"items": len(items), "outbox": channels_done,
            "audit": len(audit), "queries": len(queries)}
