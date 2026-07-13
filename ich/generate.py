"""Fase 2 — generazione proattiva di bozze dagli argomenti editoriali.

Per un argomento attivo, il motore genera una BOZZA di scheda informativa
territoriale, **ancorata alla knowledge base** (Serbatoio 1) così è fattuale e può
citare le fonti. La bozza è un CANDIDATO come gli altri: entra nella pipeline e
passa da Guardrail + validazione umana prima di qualunque dispatch. Niente
auto-pubblicazione.

Vincoli (bando): contenuti territoriali/collettivi, mai marchi commerciali; NON
inventare eventi, date, orari o prezzi → contenuto evergreen/descrittivo.

Questo modulo tiene la logica PURA (prompt + costruzione del candidato). La
chiamata al modello vive in app.py (che possiede il client Anthropic), così qui
non ci sono dipendenze e i pezzi restano testabili.
"""
from __future__ import annotations

# id base alto per non collidere con seed (<100), live (1000+) o altro
GEN_ID_BASE = 5000

GEN_SYS = """Sei il motore di generazione contenuti del Content Intelligence Hub per la promozione turistica pubblica dell'Abruzzo.
Dato un ARGOMENTO e il CONTESTO dalla knowledge base territoriale, scrivi una breve scheda informativa evergreen su quel tema in Abruzzo.
Regole ferree:
- Solo informazioni territoriali e collettive; NON promuovere imprese, hotel o marchi commerciali specifici.
- NON inventare eventi, date, orari o prezzi. Il contenuto è descrittivo e atemporale, non l'annuncio di un evento.
- Basati sul CONTESTO fornito; resta fedele a luoghi e fonti citati nel contesto.
- Tono accogliente e istituzionale, 3-5 frasi.
Rispondi SOLO con JSON valido, senza testo aggiuntivo:
{"title":"titolo breve","body":"testo della scheda","category":"una tra: natura, agroalimentare, borghi, cammini, identita, eventi, costa, trasporti"}"""


def build_user_prompt(topic: dict, kb_ctx: str) -> str:
    """Prompt utente: l'argomento + il contesto KB da cui ancorare la generazione."""
    kws = ", ".join(topic.get("keywords", []))
    return (f"ARGOMENTO: {topic.get('label', '')}\n"
            f"Parole chiave: {kws}\n"
            f"{kb_ctx or '(nessun contesto KB disponibile: resta generico e prudente)'}")


def to_candidate(topic: dict, parsed: dict, idx: int) -> dict | None:
    """Trasforma la risposta del modello in un item candidato per la pipeline
    (stesso schema del feed). Ritorna None se il titolo/corpo mancano."""
    if not parsed:
        return None
    title = (parsed.get("title") or "").strip()
    body = (parsed.get("body") or "").strip()
    if not title or not body:
        return None
    # categoria: quella suggerita dal modello, con fallback a quella dell'argomento;
    # così la bozza combacia col proprio tema già nella coda (badge di rilevanza).
    gen_cat = (parsed.get("category") or "").strip().lower() or (topic.get("category") or "")
    return {
        "id": GEN_ID_BASE + idx,
        "source": "ICH · Bozza generata",
        "icon": "✨",
        "type": "NEWS",
        "title": title,
        "raw": body,
        "detected": "bozza AI",
        "live": False,
        "generated": True,
        "topic": topic.get("label", ""),
        "category": [gen_cat] if gen_cat else [],   # usata dal tag argomenti in coda
        "gen_category": gen_cat,
        "url": "",
    }
