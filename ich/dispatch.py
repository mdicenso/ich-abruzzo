"""Dispatch — dalle varianti normalizzate ai canali reali (Step 6 della pipeline).

Passo 2 dell'architettura: il primo canale con uno sbocco REALE è l'API, cioè un
feed JSON versionato (`data/published/feed.json`) che sopravvive al reload ed è
consumabile da Abruzzo Wild. Gli altri canali (chatbot, mobile, signage, tv)
restano per ora renderizzati nella UI ma senza sink persistente: verranno estratti
a renderer/sink separati nel Passo 3 (registro canali).

All'approvazione dell'operatore, `publish()`:
1. costruisce il CanonicalItem dall'item della pipeline (+ analisi + guardrail);
2. lo persiste nello store items.json;
3. rende il payload API e lo scrive (dedup per id) nel feed pubblicato;
4. registra la decisione nell'audit log durevole (EU AI Act).

Nessuna dipendenza extra.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ich import model, store


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def map_analysis(canonical: dict, analysis: dict | None) -> dict:
    """Travasa l'output di ANALYSIS_PROMPT nei campi canonici (in place)."""
    if not analysis:
        return canonical
    if analysis.get("languages"):
        canonical["languages"] = analysis["languages"]
    try:
        canonical["importance"] = int(analysis.get("importance", canonical["importance"]))
    except (TypeError, ValueError):
        pass
    ent = analysis.get("entities") or {}
    canonical["entities"] = {
        "luoghi": ent.get("luoghi", []),
        "date": ent.get("date", []),
        "eventi": ent.get("eventi", []),
    }
    # topic → category, ma solo i valori dentro la tassonomia chiusa (gli altri si
    # scartano: category resta preciso; l'arricchimento fine è compito del Passo 4).
    topics = [str(t).lower() for t in (analysis.get("topics") or [])]
    canonical["category"] = [t for t in topics if t in model.TAXONOMY]
    return canonical


def render_api(canonical: dict, channels: dict | None = None) -> dict:
    """CanonicalItem → payload del canale API (una voce del feed pubblico)."""
    prov = canonical.get("provenance", {})
    return {
        "id": canonical["id"],
        "type": canonical.get("type"),
        "title": canonical.get("title"),
        "summary": (canonical.get("body") or "")[:400],
        "category": canonical.get("category", []),
        "when": canonical.get("when", {}),
        "where": canonical.get("where", {}),
        "languages": canonical.get("languages", []),
        "source": prov.get("source_label"),
        "url": prov.get("url"),
        "published_at": _now_iso(),
        # se il Rewriting ha prodotto un blocco 'api' strutturato, lo si allega tale e quale
        "channel_payload": (channels or {}).get("api"),
    }


def publish(item: dict, analysis: dict | None, guardrail: dict | None,
            channels: dict | None, actor: str = "operator") -> dict:
    """Dispatch reale all'approvazione. Ritorna l'entry scritta nel feed.

    Solleva se la scrittura su disco fallisce: il chiamante (app.py) decide come
    degradare, così l'errore non passa inosservato ma non azzera la sessione.
    """
    canonical = model.from_feed_item(item)
    canonical = map_analysis(canonical, analysis)
    canonical["governance"].update({
        "guardrail": (guardrail or {}).get("overall"),
        "guardrail_detail": guardrail,
        "approval": "approved",
        "approved_by": actor,
        "approved_at": _now_iso(),
    })
    store.upsert_item(canonical)  # store normalizzato (items.json)

    entry = render_api(canonical, channels)
    feed = [e for e in store.load_feed() if e.get("id") != entry["id"]]  # dedup per id
    feed.insert(0, entry)
    store.save_feed(feed)  # uscita reale (feed.json)

    store.append_audit(
        "published", canonical["id"],
        canonical["provenance"].get("source_label", ""),
        f"Dispatch canale API — feed a {len(feed)} contenuti", actor=actor,
    )
    return entry
