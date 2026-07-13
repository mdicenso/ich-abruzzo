"""Dispatch — dalle varianti normalizzate ai canali reali (Step 6 della pipeline).

Dal Passo 3 il dispatch è guidato dal **registro canali** (`ich/channels.py`):
`publish()` non conosce i singoli canali, itera su `channels.CHANNELS`. Ogni canale
rende il suo payload e lo scrive nel proprio outbox durevole in `data/published/`.

All'approvazione dell'operatore, `publish()`:
1. costruisce il CanonicalItem dall'item della pipeline (+ analisi + guardrail);
2. lo persiste nello store items.json;
3. per ogni canale del registro: renderer → sink (outbox versionato);
4. registra la decisione nell'audit log durevole (EU AI Act).

Un canale che fallisce il sink non blocca gli altri (viene annotato nell'audit).
Nessuna dipendenza extra.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ich import channels, model, store, topics


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


def persist_pipeline_item(item: dict, analysis: dict | None, guardrail: dict | None,
                          approval: str = "pending", actor: str = "system") -> dict:
    """Costruisce il CanonicalItem dai risultati della pipeline e lo salva in
    items.json col dato stato di governance. Ritorna il canonico.

    È il punto unico di persistenza: lo usano sia le fasi intermedie (guardrail →
    pending/blocked) sia le decisioni finali (rejected, e approved via publish).
    Così items.json diventa un ledger completo di tutto ciò che entra in pipeline.
    """
    canonical = model.from_feed_item(item)
    map_analysis(canonical, analysis)
    # Tag editoriale: quali argomenti (config operatore) combaciano + rilevanza.
    m = topics.match_item(canonical)
    canonical["topics_matched"] = m["matched"]
    canonical["relevance"] = m["score"]
    canonical["governance"].update({
        "guardrail": (guardrail or {}).get("overall"),
        "guardrail_detail": guardrail,
        "approval": approval,
    })
    if approval == "approved":
        canonical["governance"]["approved_by"] = actor
        canonical["governance"]["approved_at"] = _now_iso()
    store.upsert_item(canonical)
    return canonical


def publish(item: dict, analysis: dict | None, guardrail: dict | None,
            variants: dict | None, actor: str = "operator") -> dict:
    """Dispatch reale all'approvazione, guidato dal registro canali.

    `variants` è l'output del Rewriting AI (una voce per canale, può mancare).
    Ritorna un dict {channel_id: payload} con ciò che è stato dispacciato.
    """
    canonical = persist_pipeline_item(item, analysis, guardrail,
                                      approval="approved", actor=actor)

    source = canonical["provenance"].get("source_label", "")
    outputs: dict[str, dict] = {}
    failed: list[str] = []
    for ch in channels.CHANNELS:
        variant = (variants or {}).get(ch.id)
        payload = ch.renderer(canonical, variant)
        try:
            ch.sink(payload)  # scrive l'outbox durevole del canale
        except Exception:  # noqa: BLE001 — un canale non blocca gli altri
            failed.append(ch.id)
        outputs[ch.id] = payload

    ok = len(channels.CHANNELS) - len(failed)
    detail = f"Dispatch su {ok}/{len(channels.CHANNELS)} canali"
    if failed:
        detail += f" · falliti: {', '.join(failed)}"
    store.append_audit("published", canonical["id"], source, detail,
                       actor=actor, title=canonical.get("title", ""))
    return outputs
