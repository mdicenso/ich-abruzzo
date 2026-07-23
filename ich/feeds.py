"""Gestione delle fonti/feed del Serbatoio 2 — durevole e modificabile dalla UI.

Prima le fonti vivevano solo in data/feed/sources_config.json (versionato nel
repo): aggiungerne una era un'operazione *di codice* (commit + redeploy). Ora
sono **dato gestibile**: la pagina "Gestione dati" può elencarle, abilitarle e
aggiungerne di nuove (URL + descrizione), e la modifica **persiste**:

- su **Postgres** (tabella feed_sources) quando `ICH_DATABASE_URL` è configurata
  → sopravvive ai redeploy del cloud;
- su **JSON** (sources_config.json) in locale, come prima.

Alla prima connessione al DB, se la tabella è vuota viene **seminata** dalle
fonti del JSON, così non si parte mai da zero.

Il resto del motore (ich/sources.py: fetch_live/connettori) legge le fonti da qui
tramite `list_enabled()`: cambiare backend non tocca gli ingestori.

Nota sul nome del campo di mappatura: verso i connettori e nel JSON è `map`
(compat. storica); la colonna Postgres è `field_map`. La conversione avviene solo
al confine del DB, dentro questo modulo.
"""
from __future__ import annotations

import json
from pathlib import Path

from ich import model, store

_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / "data" / "feed" / "sources_config.json"

# Campi canonici di una fonte (verso la UI e i connettori usa `map`).
_FIELDS = ("id", "name", "source", "icon", "type", "kind", "url", "path",
           "map", "description", "note", "enabled", "verified")


def _feed_id(feed: dict) -> str:
    """id stabile di una fonte: slug del nome (o dell'URL) — per gestirla dalla UI."""
    base = feed.get("name") or feed.get("source") or feed.get("url") or "fonte"
    return model._slugify(base)


def _normalize(feed: dict) -> dict:
    """Riporta una voce (da JSON o DB) alla forma canonica, con id e default."""
    out = {k: feed.get(k) for k in _FIELDS}
    if not out.get("id"):
        out["id"] = _feed_id(feed)
    out["map"] = feed.get("map") or feed.get("field_map") or {}
    out["kind"] = out.get("kind") or "rss"
    out["type"] = out.get("type") or "NEWS"
    out["icon"] = out.get("icon") or "📰"
    out["enabled"] = feed.get("enabled", True)
    out["description"] = out.get("description") or out.get("note") or ""
    return out


# ─── Backend JSON ─────────────────────────────────────────────────────────────
def _json_read_raw() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"feeds": []}


def _json_list() -> list[dict]:
    return [_normalize(f) for f in _json_read_raw().get("feeds", [])]


def _json_write(feeds: list[dict]) -> None:
    raw = _json_read_raw()
    raw["feeds"] = [_to_json_feed(f) for f in feeds]
    store._atomic_write(CONFIG_PATH, json.dumps(raw, ensure_ascii=False, indent=2))


def _to_json_feed(feed: dict) -> dict:
    """Serializza una fonte per il file JSON, omettendo i campi vuoti (file pulito)."""
    out = {}
    for k in ("id", "name", "source", "icon", "type", "kind", "url", "path",
              "description", "note", "verified"):
        v = feed.get(k)
        if v:
            out[k] = v
    if feed.get("map"):
        out["map"] = feed["map"]
    out["enabled"] = bool(feed.get("enabled", True))
    return out


# ─── Backend Postgres (con seeding dal JSON) ──────────────────────────────────
def _pg_to_feed(row: dict) -> dict:
    row = dict(row)
    row["map"] = row.pop("field_map", None) or {}
    return _normalize(row)


def _feed_to_pg(feed: dict) -> dict:
    f = _normalize(feed)
    f["field_map"] = f.pop("map", {}) or {}
    return f


def _seed_pg_if_empty(pg) -> None:
    if pg.count_feed_sources() == 0:
        for f in _json_list():
            pg.upsert_feed_source(_feed_to_pg(f))


# ─── API pubblica (usata da app.py e da sources.py) ───────────────────────────
def list_all() -> list[dict]:
    """Tutte le fonti (abilitate o no), forma canonica con `id` e `map`."""
    pg = store._backend()
    if pg is not None:
        try:
            _seed_pg_if_empty(pg)
            return [_pg_to_feed(r) for r in pg.list_feed_sources()]
        except Exception:
            pass
    return _json_list()


def list_enabled() -> list[dict]:
    """Solo le fonti abilitate — è ciò che ingerisce il motore (fetch_live)."""
    return [f for f in list_all() if f.get("enabled", True)]


def add_source(feed: dict) -> dict:
    """Aggiunge/aggiorna una fonte (per id). Ritorna la fonte normalizzata."""
    f = _normalize(feed)
    pg = store._backend()
    if pg is not None:
        try:
            pg.upsert_feed_source(_feed_to_pg(f))
            return f
        except Exception:
            pass
    feeds = _json_list()
    feeds = [x for x in feeds if x.get("id") != f["id"]] + [f]
    _json_write(feeds)
    return f


def set_enabled(feed_id: str, enabled: bool) -> None:
    pg = store._backend()
    if pg is not None:
        try:
            pg.set_feed_enabled(feed_id, bool(enabled))
            return
        except Exception:
            pass
    feeds = _json_list()
    for f in feeds:
        if f.get("id") == feed_id:
            f["enabled"] = bool(enabled)
    _json_write(feeds)


def delete_source(feed_id: str) -> None:
    pg = store._backend()
    if pg is not None:
        try:
            pg.delete_feed_source(feed_id)
            return
        except Exception:
            pass
    feeds = [f for f in _json_list() if f.get("id") != feed_id]
    _json_write(feeds)
