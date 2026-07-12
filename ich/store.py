"""Store versionati nel repo — persistenza del motore ICH.

Disco Streamlit Cloud effimero → lo stato del dispatcher vive in file JSON
versionati nel repo (decisione architettura §7). Tre store:

- data/store/items.json    : i CanonicalItem normalizzati (pending/approved)
- data/published/feed.json : l'uscita reale del dispatch (canale API, consumabile
                             da Abruzzo Wild)
- data/store/audit.jsonl   : log append-only delle decisioni (EU AI Act)

Nessuna dipendenza extra. Scritture atomiche (tmp + os.replace) per non lasciare
file mezzo-scritti se il processo si interrompe. Le letture non sollevano mai:
un file assente/corrotto ritorna un default vuoto, così l'app resta viva.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = _ROOT / "data" / "store"
PUBLISHED_DIR = _ROOT / "data" / "published"
ITEMS_PATH = STORE_DIR / "items.json"
FEED_PATH = PUBLISHED_DIR / "feed.json"
AUDIT_PATH = STORE_DIR / "audit.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dirs() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str) -> None:
    _ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)  # atomico sullo stesso filesystem


# ─── Items normalizzati ───────────────────────────────────────────────────────
def load_items() -> list[dict]:
    try:
        with open(ITEMS_PATH, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def save_items(items: list[dict]) -> None:
    payload = {"updated_at": _now_iso(), "count": len(items), "items": items}
    _atomic_write(ITEMS_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def upsert_item(item: dict) -> list[dict]:
    """Inserisce o aggiorna un item per `id` (dedup), preservando l'ordine.
    Ritorna la lista completa aggiornata."""
    items = load_items()
    iid = item.get("id")
    for i, existing in enumerate(items):
        if existing.get("id") == iid:
            items[i] = item
            break
    else:
        items.append(item)
    save_items(items)
    return items


def get_item(item_id: str) -> dict | None:
    for it in load_items():
        if it.get("id") == item_id:
            return it
    return None


# ─── Feed pubblicato (canale API) ─────────────────────────────────────────────
def load_feed() -> list[dict]:
    try:
        with open(FEED_PATH, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def save_feed(entries: list[dict]) -> None:
    payload = {
        "feed": "ICH Abruzzo — contenuti istituzionali approvati",
        "updated_at": _now_iso(),
        "count": len(entries),
        "items": entries,
    }
    _atomic_write(FEED_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


# ─── Audit log (EU AI Act) ────────────────────────────────────────────────────
def append_audit(event: str, item_id: str, source: str, detail: str,
                 actor: str = "system") -> dict:
    """Aggiunge una riga al log append-only. `actor`: 'system' | 'operator'."""
    _ensure_dirs()
    entry = {"ts": _now_iso(), "event": event, "item_id": item_id,
             "source": source, "actor": actor, "detail": detail}
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_audit(limit: int | None = None) -> list[dict]:
    """Ritorna le righe del log, più recenti prima."""
    try:
        with open(AUDIT_PATH, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []
    rows.reverse()
    return rows[:limit] if limit else rows
