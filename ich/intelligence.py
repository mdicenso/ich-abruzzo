"""Serbatoio 3 — Destination & Demand Intelligence + Intelligence operativa.

Fonti REALI, niente numeri inventati:
1. Destination intelligence (macro): snapshot ISTAT/Banca d'Italia generato dalla
   cache del progetto TDH → data/intelligence/abruzzo_destination.json.
2. Demand intelligence (micro): le query reali poste all'assistente → topic
   richiesti e "content gap" (domande senza risposta nel KB), ora durevoli.
3. Intelligence operativa (Passo 6): legge ciò che il motore/dispatcher (B) ha
   prodotto — il ledger `items.json` e l'audit — per dare funnel della pipeline e
   copertura editoriale (offerta per tassonomia vs gap tematici).
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from ich import model  # tassonomia chiusa per la copertura editoriale

SNAP_PATH = Path(__file__).resolve().parent.parent / "data" / "intelligence" / "abruzzo_destination.json"


@lru_cache(maxsize=1)
def load_destination() -> dict:
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def destination_kpi() -> dict:
    """KPI macro reali. Ritorna dict vuoto se lo snapshot manca."""
    d = load_destination()
    annue = d.get("presenze_annue", {})
    if not annue:
        return {}
    anni = sorted(annue, key=lambda x: int(x))
    ultimo = anni[-1]
    pres_ultimo = annue[ultimo]
    # recupero rispetto al pre-Covid (2019) se disponibile
    base = annue.get("2019")
    delta_2019 = round((pres_ultimo / base - 1) * 100) if base else None
    letti = d.get("posti_letto", {})
    spesa = d.get("spesa_stranieri_milioni", {})
    return {
        "anno": ultimo,
        "presenze": pres_ultimo,
        "delta_2019": delta_2019,
        "posti_letto": letti.get(ultimo) or (list(letti.values())[-1] if letti else None),
        "spesa_stranieri": spesa.get(ultimo) or (list(spesa.values())[-1] if spesa else None),
    }


# ── Demand intelligence dalle query reali dell'assistente ──

_CAT_LABEL = {
    "enogastronomia": "Enogastronomia", "borghi": "Borghi storici", "natura": "Natura e parchi",
    "cammini": "Cammini e trekking", "costa": "Mare e costa", "cultura": "Cultura ed eventi",
    "fauna": "Fauna", "esperienze": "Esperienze",
}


def topics_from_log(log: list[dict], top: int = 6) -> list[dict]:
    """Topic più richiesti, dedotti dalle categorie KB recuperate per ogni query."""
    cnt = Counter()
    for entry in log:
        for cat in entry.get("categories", []):
            cnt[cat] += 1
    return [{"Topic": _CAT_LABEL.get(c, c.capitalize()), "Query": n}
            for c, n in cnt.most_common(top)]


def gaps_from_log(log: list[dict], top: int = 8) -> list[dict]:
    """Content gap reali: domande che NON hanno trovato nulla nel knowledge base."""
    cnt = Counter()
    for entry in log:
        if not entry.get("answered"):
            q = (entry.get("q") or "").strip()
            if q:
                cnt[q] += 1
    return [{"Domanda": q, "N": n} for q, n in cnt.most_common(top)]


# ── Intelligence operativa: legge il ledger prodotto dal dispatcher (Passo 6) ──

_TAX_LABEL = {
    "natura": "Natura e parchi", "agroalimentare": "Enogastronomia",
    "borghi": "Borghi", "cammini": "Cammini", "identita": "Identità e cultura",
    "eventi": "Eventi", "costa": "Costa e mare", "trasporti": "Trasporti",
}


def pipeline_stats(items: list[dict]) -> dict:
    """Funnel della pipeline dal ledger items.json: quanti item processati e come
    si distribuiscono per esito guardrail e stato di approvazione."""
    def g(it):
        return it.get("governance", {})
    return {
        "total": len(items),
        "guardrail_pass": sum(1 for i in items if g(i).get("guardrail") in ("pass", "warn")),
        "guardrail_blocked": sum(1 for i in items if g(i).get("guardrail") == "blocked"),
        "approved": sum(1 for i in items if g(i).get("approval") == "approved"),
        "rejected": sum(1 for i in items if g(i).get("approval") == "rejected"),
        "pending": sum(1 for i in items if g(i).get("approval") == "pending"),
    }


def category_coverage(items: list[dict]) -> list[dict]:
    """Copertura editoriale: quanti contenuti APPROVATI per ogni tema della
    tassonomia. Include le categorie a zero (= gap tematico da riempire)."""
    cnt = Counter()
    for it in items:
        if it.get("governance", {}).get("approval") == "approved":
            for c in it.get("category", []):
                cnt[c] += 1
    return [{"cat": c, "label": _TAX_LABEL.get(c, c.capitalize()), "n": cnt.get(c, 0)}
            for c in model.TAXONOMY]
