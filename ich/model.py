"""Schema canonico dell'item — la forma normalizzata su cui tutto ICH si accorda.

L'ingestione (Serbatoio 2 / connettori) converte le fonti disparate *verso* il
CanonicalItem; il dispatch converte *da* esso verso i canali. Un solo oggetto,
un solo posto per ogni informazione.

Vedi docs/architettura-ich.md §4-5. Nessuna dipendenza extra (solo stdlib), così
gira anche sul disco effimero di Streamlit Cloud.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

# ─── Vocabolari chiusi ────────────────────────────────────────────────────────
# Tassonomia dal bando (fonti-dati-ich.md): usata da guardrail, routing, Intelligence.
TAXONOMY = (
    "natura", "agroalimentare", "borghi", "cammini",
    "identita", "eventi", "costa", "trasporti",
)
# Tipi di contenuto ingeribili.
ITEM_TYPES = ("EVENTO", "NEWS", "AVVISO", "TRASPORTI", "SAGRA", "PROMO")
GUARDRAIL_STATES = ("pass", "warn", "blocked")
APPROVAL_STATES = ("pending", "approved", "rejected")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:limit].strip("-") or "fonte"


def canonical_id(source_id: str, date_str: str, title: str) -> str:
    """id deterministico = hash di (fonte + data + titolo) — decisione §11.3.

    Stesso contenuto dalla stessa fonte → stesso id → dedup reale. `date_str` va
    passato SOLO se stabile (es. pubDate ISO): un valore instabile (tempo relativo
    '5 min fa') romperebbe il determinismo, quindi in sua assenza si passa "" e il
    dedup ricade su (fonte + titolo), comunque stabile.
    """
    base = f"{source_id}|{date_str or ''}|{(title or '').strip().lower()}"
    return "itm_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]


# ─── Lo schema ────────────────────────────────────────────────────────────────
@dataclass
class CanonicalItem:
    """Contenuto normalizzato. I campi si riempiono in fasi successive:
    ingestione → (provenance, type, title, body); normalizzazione → (category,
    entities, when, where, languages, importance, governance.guardrail);
    approvazione → (governance.approval)."""

    id: str
    type: str = "NEWS"
    title: str = ""
    body: str = ""
    provenance: dict = field(default_factory=dict)  # source_id, source_kind, url, ingested_at
    category: list = field(default_factory=list)     # sottoinsieme di TAXONOMY
    entities: dict = field(default_factory=lambda: {"luoghi": [], "date": [], "eventi": []})
    when: dict = field(default_factory=lambda: {"start": None, "end": None})
    where: dict = field(default_factory=lambda: {"comune": None, "prov": None, "geo": None})
    languages: list = field(default_factory=lambda: ["IT"])
    importance: int = 5
    topics_matched: list = field(default_factory=list)  # argomenti editoriali che combaciano
    relevance: int = 0                                   # rilevanza pesata per priorità
    governance: dict = field(default_factory=lambda: {
        "guardrail": None,          # pass|warn|blocked
        "guardrail_detail": None,   # i 6 check
        "approval": "pending",      # pending|approved|rejected
        "approved_by": None,
        "approved_at": None,
    })

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalItem":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


def from_feed_item(raw_item: dict) -> dict:
    """Costruisce lo *shell* canonico (come dict) da un item del feed Serbatoio 2.

    Riempie provenienza, tipo, titolo, body con id deterministico. I campi di
    normalizzazione restano ai default (`governance.approval == 'pending'`):
    li popolerà la fase di normalizzazione. Il resto del codice ICH lavora su
    dict, quindi qui si ritorna un dict, non l'oggetto.
    """
    source_label = raw_item.get("source", "Fonte")
    source_id = raw_item.get("source_id") or _slugify(source_label)
    title = (raw_item.get("title") or "").strip()
    # Solo una data STABILE entra nell'id (vedi canonical_id). Il tempo relativo
    # 'detected' non è stabile e va escluso: si userà il pubDate quando disponibile.
    date_for_id = raw_item.get("pubdate_iso") or ""
    item = CanonicalItem(
        id=canonical_id(source_id, date_for_id, title),
        type=(raw_item.get("type") or "NEWS").upper(),
        title=title,
        body=(raw_item.get("raw") or raw_item.get("body") or title),
        provenance={
            "source_id": source_id,
            "source_kind": raw_item.get("source_kind") or ("rss" if raw_item.get("live") else "seed"),
            "source_label": source_label,
            "url": raw_item.get("url", ""),
            "ingested_at": _now_iso(),
        },
    )
    return item.to_dict()
