"""Serbatoio 1 — Knowledge Base territoriale dell'Abruzzo.

Carica la base conoscitiva curata (data/kb/abruzzo_kb.json) ed espone un
recupero leggero (RAG-lite) per parole-chiave: niente vector DB né dipendenze
extra, così gira anche sul disco effimero di Streamlit Cloud.

Il recupero non vuole essere semantico-perfetto: deve fornire all'assistente
alcuni chunk pertinenti + la fonte, così le risposte sono fedeli e citabili.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "kb" / "abruzzo_kb.json"

# Stopword italiane/inglesi minime: parole troppo comuni che non aiutano il match.
_STOP = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in",
    "con", "su", "per", "tra", "fra", "e", "ed", "o", "ma", "che", "chi", "cosa",
    "come", "dove", "quando", "qual", "quali", "quale", "ci", "si", "non", "del",
    "della", "dei", "delle", "degli", "al", "alla", "ai", "alle", "dal", "dalla",
    "nel", "nella", "sul", "sulla", "è", "sono", "c", "mi", "ti", "vorrei", "posso",
    "dimmi", "voglio", "the", "a", "an", "of", "to", "in", "is", "are", "what",
    "where", "how", "can", "i", "me", "my", "and", "or", "for", "with",
}

# Sinonimi/espansioni: la domanda dell'utente e il KB non usano sempre le stesse
# parole. Mappa termini comuni della domanda → termini presenti nei chunk.
_SYNONYMS = {
    "mangiare": ["enogastronomia", "cibo", "piatto", "tradizione"],
    "mangio": ["enogastronomia", "cibo", "piatto"],
    "cibo": ["enogastronomia", "piatto", "prodotto"],
    "cucina": ["enogastronomia", "piatto", "tradizione"],
    "vino": ["vino", "enogastronomia"],
    "bere": ["vino", "enogastronomia"],
    "trekking": ["escursionismo", "sentieri", "cammino", "montagna"],
    "hiking": ["escursionismo", "sentieri", "montagna"],
    "escursione": ["escursionismo", "sentieri", "montagna"],
    "camminare": ["cammino", "sentieri", "trekking"],
    "montagna": ["montagna", "parco", "natura"],
    "sci": ["sci", "inverno", "neve"],
    "sciare": ["sci", "inverno", "neve"],
    "mare": ["costa", "spiaggia", "mare"],
    "spiaggia": ["costa", "spiaggia", "mare"],
    "spiagge": ["costa", "spiaggia", "mare"],
    "bambini": ["esperienze", "fattorie", "famiglia"],
    "famiglia": ["esperienze", "famiglia"],
    "borgo": ["borghi", "borgo", "medievale"],
    "borghi": ["borghi", "borgo", "medievale"],
    "evento": ["cultura", "evento", "rievocazione"],
    "eventi": ["cultura", "evento"],
    "animali": ["fauna"],
    "fauna": ["fauna"],
    "orso": ["orso", "fauna"],
    "terme": ["terme", "benessere"],
    "relax": ["terme", "benessere"],
    "grotte": ["grotte"],
    "lago": ["lago"],
    "laghi": ["lago"],
}


def _stem(t: str) -> str:
    """Stemming leggerissimo: toglie la vocale finale alle parole lunghe, così
    singolare e plurale collidono (orso/orsi→ors, vino/vini→vin)."""
    if len(t) > 3 and t[-1] in "aeiouàèéìòóùü":
        return t[:-1]
    return t


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-zàèéìòóùü0-9]+", (text or "").lower())
    return [_stem(t) for t in toks if t not in _STOP and len(t) > 2]


@lru_cache(maxsize=1)
def load_kb() -> dict:
    """Carica il KB dal disco (una sola volta)."""
    try:
        with open(KB_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"meta": {}, "chunks": []}
    # Pre-tokenizza ogni chunk per il match (title e tags pesano di più).
    for c in data.get("chunks", []):
        searchable = " ".join([
            c.get("title", ""), c.get("title", ""),          # title ×2
            " ".join(c.get("tags", [])), " ".join(c.get("tags", [])),  # tags ×2
            c.get("category", ""), c.get("area", ""), c.get("text", ""),
        ])
        c["_tokens"] = _tokenize(searchable)
    return data


def kb_stats() -> dict:
    kb = load_kb()
    chunks = kb.get("chunks", [])
    cats = {}
    for c in chunks:
        cats[c.get("category", "altro")] = cats.get(c.get("category", "altro"), 0) + 1
    return {"n_chunks": len(chunks), "categorie": cats,
            "versione": kb.get("meta", {}).get("versione", "?")}


def _expand_query(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    for t in tokens:
        # i sinonimi sono indicizzati per parola intera; provo sia il token
        # stemmato sia, per sicurezza, le chiavi che iniziano con lo stesso stem.
        for key, syns in _SYNONYMS.items():
            if _stem(key) == t:
                expanded.extend(_stem(s) for s in syns)
    return expanded


def retrieve(query: str, k: int = 5) -> list[dict]:
    """Ritorna i k chunk più pertinenti alla query (lista di dict del KB).

    Punteggio = somma delle occorrenze, nei token del chunk, dei token della
    query (espansi con i sinonimi). Nessun match → lista vuota.
    """
    kb = load_kb()
    chunks = kb.get("chunks", [])
    q_tokens = _expand_query(_tokenize(query))
    if not q_tokens or not chunks:
        return []
    scored = []
    for c in chunks:
        ctoks = c.get("_tokens", [])
        if not ctoks:
            continue
        score = sum(ctoks.count(qt) for qt in q_tokens)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


def build_context(query: str, k: int = 5) -> tuple[str, list[dict]]:
    """Costruisce il blocco di contesto da iniettare nel system prompt.

    Ritorna (testo_contesto, chunk_usati). Se non trova nulla, testo vuoto.
    """
    hits = retrieve(query, k=k)
    if not hits:
        return "", []
    righe = ["\nCONTESTO DAL KNOWLEDGE BASE TERRITORIALE (usa queste informazioni e cita la fonte tra parentesi quadre):"]
    for c in hits:
        righe.append(f"- [{c.get('source','fonte')}] {c.get('title','')}: {c.get('text','')}")
    return "\n".join(righe), hits
