"""Argomenti editoriali — cosa il motore deve seguire (controllo dell'operatore).

L'operatore definisce gli *argomenti* di interesse in `data/config/topics.json`,
gestiti dalla pagina "Argomenti". Ogni argomento ha keyword ed (opzionale) una
categoria della tassonomia, più una priorità.

Fase 1 (filtro/priorità): `match_item()` tagga un contenuto con gli argomenti che
combaciano e ne calcola la RILEVANZA (pesata per priorità) → l'info feed si
focalizza sui temi scelti e la coda si può ordinare per rilevanza.
Fase 2 (futura): gli stessi argomenti guideranno ricerca/generazione proattiva.

Nessuna dipendenza extra (stdlib). La persistenza riusa lo store del motore.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ich import store  # riuso della scrittura atomica resiliente

_ROOT = Path(__file__).resolve().parent.parent
TOPICS_PATH = _ROOT / "data" / "config" / "topics.json"

PRIORITY_WEIGHT = {"alta": 3, "media": 2, "bassa": 1}


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return s[:40] or "argomento"


def default_topics() -> list[dict]:
    """8 argomenti di partenza, uno per tema della tassonomia."""
    base = [
        ("Natura e parchi", "natura", ["parco", "sentiero", "montagna", "natura", "riserva", "vetta"]),
        ("Enogastronomia", "agroalimentare", ["vino", "sagra", "prodotto", "dop", "tipico", "arrosticini", "cantina"]),
        ("Borghi", "borghi", ["borgo", "medievale", "castello", "rocca", "centro storico"]),
        ("Cammini e trekking", "cammini", ["cammino", "trekking", "sentiero", "pellegrino", "tappa"]),
        ("Identità e cultura", "identita", ["tradizione", "rievocazione", "festa", "storico", "mostra", "museo"]),
        ("Eventi", "eventi", ["evento", "festival", "concerto", "spettacolo", "fiera"]),
        ("Costa e mare", "costa", ["mare", "spiaggia", "costa", "trabocco", "bandiera blu"]),
        ("Trasporti", "trasporti", ["treno", "bus", "strada", "viabilità", "collegamento", "navetta"]),
    ]
    return [{"id": _slug(lbl), "label": lbl, "category": cat,
             "keywords": kws, "priority": "media", "enabled": True}
            for lbl, cat, kws in base]


# ─── Persistenza pluggable (JSON locale o Postgres, come lo store del motore) ──
def _json_load_topics() -> list[dict]:
    """Argomenti dal file; se manca/è vuoto, ritorna i default (senza scriverli)."""
    try:
        with open(TOPICS_PATH, encoding="utf-8") as f:
            topics = json.load(f).get("topics", [])
            return topics if topics else default_topics()
    except Exception:
        return default_topics()


def _json_save_topics(topics: list[dict]) -> None:
    TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"topics": topics}
    store._atomic_write(TOPICS_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def load_topics() -> list[dict]:
    """Argomenti dal backend attivo. Su Postgres: se la tabella è vuota viene
    **seminata** una volta dal JSON esistente (o dai default), così le modifiche
    fatte in UI persistono ai redeploy del cloud. In locale: dal file JSON."""
    pg = store._backend()
    if pg is not None:
        try:
            rows = pg.list_topics()
            if not rows:
                seed = _json_load_topics()
                pg.save_topics(seed)
                return seed
            return rows
        except Exception:
            pass
    return _json_load_topics()


def save_topics(topics: list[dict]) -> None:
    pg = store._backend()
    if pg is not None:
        try:
            pg.save_topics(topics)
            return
        except Exception:
            pass
    _json_save_topics(topics)


def active_topics() -> list[dict]:
    return [t for t in load_topics() if t.get("enabled", True)]


def _text_of(item: dict) -> str:
    """Testo su cui cercare le keyword: titolo + corpo (feed item o canonico)."""
    return " ".join([
        str(item.get("title", "")),
        str(item.get("body", item.get("raw", ""))),
    ]).lower()


def _categories_of(item: dict) -> list[str]:
    cat = item.get("category", [])
    if isinstance(cat, str):
        return [cat]
    return cat or []


def match_item(item: dict, topics: list[dict] | None = None) -> dict:
    """Tagga un contenuto con gli argomenti che combaciano e ne dà la rilevanza.

    Un argomento combacia se una sua keyword compare nel testo OPPURE se la sua
    categoria è tra quelle del contenuto. La rilevanza è la somma dei pesi di
    priorità degli argomenti combacianti. Ritorna:
    {"matched": [{"id","label","priority"}], "score": int}.
    """
    topics = active_topics() if topics is None else [t for t in topics if t.get("enabled", True)]
    text = _text_of(item)
    cats = _categories_of(item)
    matched, score = [], 0
    for t in topics:
        kw_hit = any(str(kw).lower() in text for kw in t.get("keywords", []) if str(kw).strip())
        cat_hit = bool(t.get("category")) and t["category"] in cats
        if kw_hit or cat_hit:
            matched.append({"id": t.get("id"), "label": t.get("label"), "priority": t.get("priority", "media")})
            score += PRIORITY_WEIGHT.get(t.get("priority", "media"), 2)
    return {"matched": matched, "score": score}
