"""Registro canali — il dispatch come plugin (Passo 3 dell'architettura).

Ogni canale è una voce dichiarativa (id, label, kind) con due funzioni:
- **renderer(canonical, variant) -> payload**: dà forma al contenuto per quel
  canale. Usa la variante prodotta dal Rewriting AI se presente, con un fallback
  deterministico se manca (l'app gira anche senza API key).
- **sink(payload) -> None**: consegna il payload alla destinazione durevole, cioè
  un *outbox* JSON versionato in `data/published/<canale>.json` (dedup per id).

`dispatch.publish` itera su `CHANNELS` senza conoscere i singoli canali: aggiungere
un canale = una voce in più qui + il suo renderer, senza toccare il motore.

Nature dei canali:
- push: mobile, signage, tv, api → ICH spinge il contenuto verso l'outbox.
- pull: chatbot → l'assistente attinge dal suo outbox quando serve.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ich import store


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _envelope(canonical: dict, channel_id: str, content) -> dict:
    """Busta uniforme per ogni canale: metadati comuni + `content` specifico
    (stringa per i canali testuali, dict per l'API). L'`id` serve al dedup."""
    prov = canonical.get("provenance", {})
    return {
        "id": canonical["id"],
        "channel": channel_id,
        "type": canonical.get("type"),
        "title": canonical.get("title"),
        "source": prov.get("source_label"),
        "url": prov.get("url"),
        "content": content,
        "published_at": _now_iso(),
    }


# ─── Renderer (uno per canale) ────────────────────────────────────────────────
def render_chatbot(canonical: dict, variant) -> dict:
    content = variant if isinstance(variant, str) and variant.strip() else (
        f"{canonical.get('title','')} — un contenuto da non perdere in Abruzzo! "
        "Vuoi sapere come raggiungerlo o gli orari?")
    return _envelope(canonical, "chatbot", content)


def render_mobile(canonical: dict, variant) -> dict:
    title = canonical.get("title", "")
    content = variant if isinstance(variant, str) and variant.strip() else (
        f"🔔 {title[:45]}\nDettagli su abruzzoturismo.it")
    return _envelope(canonical, "mobile", content)


def render_signage(canonical: dict, variant) -> dict:
    title = canonical.get("title", "")
    src = canonical.get("provenance", {}).get("source_label", "")
    content = variant if isinstance(variant, str) and variant.strip() else (
        f"{title.upper()[:28]}\nEvento locale · Ingresso libero\n{src}")
    return _envelope(canonical, "signage", content)


def render_tv(canonical: dict, variant) -> dict:
    title = canonical.get("title", "")
    src = canonical.get("provenance", {}).get("source_label", "")
    content = variant if isinstance(variant, str) and variant.strip() else (
        f"{title}\nFonte: {src}\nwww.abruzzoturismo.it\n{_now_iso()[:10]}")
    return _envelope(canonical, "tv", content)


def render_api(canonical: dict, variant) -> dict:
    """Payload strutturato del canale API (voce del feed pubblico)."""
    content = {
        "summary": (canonical.get("body") or "")[:400],
        "category": canonical.get("category", []),
        "topics": [m.get("label") for m in canonical.get("topics_matched", [])],
        "relevance": canonical.get("relevance", 0),
        "when": canonical.get("when", {}),
        "where": canonical.get("where", {}),
        "languages": canonical.get("languages", []),
        # se il Rewriting ha prodotto un blocco 'api' strutturato, lo si allega
        "channel_payload": variant if isinstance(variant, dict) else None,
    }
    return _envelope(canonical, "api", content)


# ─── Sink (uno per canale, outbox durevole) ───────────────────────────────────
def _outbox_sink(outbox_name: str) -> Callable[[dict], None]:
    """Sink che scrive il payload nell'outbox versionato, dedup per id, più recente
    in cima. Ritorna una funzione, così ogni canale ha il suo sink pronto."""
    def sink(payload: dict) -> None:
        entries = [e for e in store.load_outbox(outbox_name) if e.get("id") != payload.get("id")]
        entries.insert(0, payload)
        store.save_outbox(outbox_name, entries)
    return sink


# ─── Il registro ──────────────────────────────────────────────────────────────
@dataclass
class Channel:
    id: str
    label: str
    icon: str
    kind: str            # "push" | "pull"
    renderer: Callable[[dict, object], dict]
    sink: Callable[[dict], None]


CHANNELS: list[Channel] = [
    Channel("chatbot", "Assistente", "💬", "pull", render_chatbot, _outbox_sink("chatbot")),
    Channel("mobile",  "Mobile",     "📱", "push", render_mobile,  _outbox_sink("mobile")),
    Channel("signage", "Signage",    "📺", "push", render_signage, _outbox_sink("signage")),
    Channel("tv",      "TV Panel",   "🖥️", "push", render_tv,      _outbox_sink("tv")),
    # il canale API scrive l'outbox storico "feed" (feed.json), nome stabile per Abruzzo Wild
    Channel("api",     "Feed API",   "⚡", "push", render_api,     _outbox_sink("feed")),
]


def by_id(channel_id: str) -> Channel | None:
    return next((c for c in CHANNELS if c.id == channel_id), None)
