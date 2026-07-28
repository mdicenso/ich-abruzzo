"""Estrazione da PDF di avvisi/comunicati istituzionali — Serbatoio 2.

Perché serve
------------
La ricognizione dei feed (vedi `docs/fonti-dati-ich.md`) ha mostrato che
l'ecosistema abruzzese pubblica pochissimo in RSS: molti avvisi comunali e di
enti vivono **solo come PDF**. Il bando GAL, del resto, ammette esplicitamente
le fonti in *«.pdf nativo (non scansioni)»* → questo è il connettore che le apre.

Strategia: **euristica prima, AI dopo**
---------------------------------------
Gli avvisi della PA hanno un impianto molto regolare ("COMUNE DI …",
"OGGETTO: …", "Prot. n. … del 12/08/2026"), quindi nella maggior parte dei casi
titolo, data e categoria si ricavano con regole deterministiche — gratis,
ripetibili e verificabili. Il modello interviene **solo sui campi rimasti vuoti**
(`needs_ai`), così l'ingestione non brucia token a ogni giro e il risultato non
cambia da un'esecuzione all'altra quando il PDF è ben fatto.

Come `generate.py`, questo modulo resta **puro**: niente client Anthropic, niente
Streamlit. La chiamata al modello è iniettata da `app.py` via
`sources.set_ai_extractor()`.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

# Tassonomia editoriale: la stessa di generate.py e degli argomenti.
# I termini sono **radici**, confrontate a inizio parola (vedi _CAT_RE): così
# "escursion" prende escursione/escursioni, ma "orso" NON scatta dentro
# "percorso" — falso positivo che classificava come 'natura' qualunque testo
# contenente la parola percorso.
CATEGORY_KEYWORDS = {
    "eventi":        ("sagra", "sagre", "festa", "feste", "concerto", "mostra",
                      "rassegna", "palio", "fiera", "processione", "spettacol",
                      "festival", "premio"),
    "agroalimentare": ("dop", "igp", "pat", "vino", "olio", "zafferano", "tartufo",
                       "arrosticin", "formaggio", "enogastronom", "prodotti tipici"),
    "natura":        ("parco", "parchi", "riserva", "sentier", "fauna", "orso",
                      "camoscio", "bosco", "montagna", "escursion", "area protetta"),
    "cammini":       ("cammin", "trattur", "pellegrin", "trekking", "ippovia"),
    "borghi":        ("borgo", "borghi", "centro storico", "castello", "eremo"),
    "costa":         ("mare", "spiaggia", "costa", "trabocc", "balnear", "porto"),
    "trasporti":     ("bus", "treno", "viabilit", "strada", "chiusura", "navetta",
                      "trasport", "parcheggio"),
    "identita":      ("tradizion", "identit", "artigian", "dialetto", "memoria",
                      "transumanza"),
}

# Una regex per categoria: alternativa delle radici ancorata a inizio parola.
_CAT_RE = {
    cat: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")", re.I)
    for cat, kws in CATEGORY_KEYWORDS.items()
}

_MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11,
    "dicembre": 12,
}

# "12/08/2026", "12-08-2026", "12.08.2026"
_DATE_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
# "12 agosto 2026"
_DATE_IT = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS_IT) + r")\s+(\d{4})\b", re.I)

# Righe di intestazione da saltare quando si cerca il titolo: non solo l'ente
# (COMUNE DI …) ma anche l'ufficio che firma (Dipartimento/Settore/Servizio…),
# che altrimenti verrebbe scambiato per il titolo dell'avviso.
_HEADER_RE = re.compile(
    r"^\s*(comune|citt[àa]|provincia|regione|unione|comunit[àa]|ente|parco|"
    r"repubblica|ministero|dipartimento|assessorato|presidenza|direzione|"
    r"settore|servizio|ufficio|area\b|prot\.?|protocollo|c\.?f\.?|p\.?\s?iva|"
    r"tel\.?|pec\b|email|www\.|http)", re.I)

# "OGGETTO: xxx" / "AVVISO PUBBLICO xxx" → il titolo è quello che segue.
_SUBJECT_RE = re.compile(
    r"^\s*(?:oggetto|avviso(?:\s+pubblico)?|comunicato(?:\s+stampa)?|bando|"
    r"ordinanza|manifestazione\s+di\s+interesse)\s*[:.\-–]?\s*(.*)$", re.I)


def extract_text(data: bytes, max_pages: int = 5) -> str:
    """Testo delle prime `max_pages` pagine di un PDF **nativo**.

    Solleva ImportError con istruzioni se manca pypdf, e ValueError se il PDF non
    contiene testo estraibile: quest'ultimo caso è quasi sempre una **scansione**
    (immagine), che il bando esclude e che servirebbe OCR per leggere.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dipende dall'ambiente
        raise ImportError(
            "Il connettore PDF richiede pypdf: `pip install pypdf` "
            "(è già in requirements.txt)") from e

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - una pagina illeggibile non blocca le altre
            continue
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("PDF senza testo estraibile (probabile scansione: serve OCR)")
    return text


def meta_title(data: bytes) -> str:
    """Titolo dai metadati del PDF, se sensato. Scarta i titoli-spazzatura che
    Word/OpenOffice lasciano di default ('Microsoft Word - avviso.doc')."""
    try:
        from pypdf import PdfReader
        t = (PdfReader(io.BytesIO(data)).metadata or {}).get("/Title") or ""
    except Exception:  # noqa: BLE001
        return ""
    t = str(t).strip()
    if not t or len(t) < 8:
        return ""
    if re.match(r"^microsoft word\s*-|\.(doc|docx|pdf|odt)$", t, re.I):
        return ""
    return t


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def guess_title(text: str, fallback: str = "") -> str:
    """Titolo dell'avviso, in ordine di affidabilità:
    1. la coda di una riga 'OGGETTO:/AVVISO:/BANDO:' (o la riga successiva);
    2. la prima riga di sostanza, saltando le intestazioni dell'ente;
    3. `fallback` (di norma il titolo dai metadati o il nome del file).
    """
    lines = _lines(text)

    for i, ln in enumerate(lines[:25]):
        m = _SUBJECT_RE.match(ln)
        if not m:
            continue
        tail = m.group(1).strip(" :.-–")
        if len(tail) >= 10:
            return tail[:160]
        # "OGGETTO:" da solo su una riga → il titolo è la riga dopo
        for nxt in lines[i + 1:i + 3]:
            if len(nxt) >= 10 and not _HEADER_RE.match(nxt):
                return nxt[:160]

    for ln in lines[:20]:
        if len(ln) >= 15 and not _HEADER_RE.match(ln) and not _DATE_NUM.fullmatch(ln):
            return ln[:160]

    return fallback[:160]


def guess_date(text: str) -> datetime | None:
    """Prima data plausibile nel testo. None se non ce n'è: interviene l'AI.

    La forma **estesa** ("14 agosto 2026") ha la precedenza su quella numerica
    di proposito: negli avvisi la data in lettere è quasi sempre quella
    dell'*evento* nel corpo del testo, mentre la numerica è tipicamente la data
    di protocollo in intestazione ("Prot. n. 3312 del 20/07/2026") — che non è
    l'informazione editorialmente interessante.
    """
    m = _DATE_IT.search(text)
    if m:
        try:
            return datetime(int(m.group(3)), _MONTHS_IT[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            pass
    for m in _DATE_NUM.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d)
        except ValueError:
            continue  # p.es. 31/02: scarta e prova la successiva
    return None


def guess_category(text: str) -> str:
    """Categoria della tassonomia con più riscontri nel testo ('' se nessuno).
    A parità di punteggio vince la categoria più specifica (ordine di
    CATEGORY_KEYWORDS), non l'ordine alfabetico."""
    scores = {cat: len(rx.findall(text)) for cat, rx in _CAT_RE.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else ""


def guess_type(text: str) -> str:
    """EVENTO se il documento annuncia una manifestazione, altrimenti NEWS."""
    return "EVENTO" if any(k in text.lower() for k in CATEGORY_KEYWORDS["eventi"]) else "NEWS"


def needs_ai(title: str, dt: datetime | None, category: str) -> bool:
    """Vero se l'euristica ha lasciato buchi → vale la pena spendere una chiamata."""
    return not title or dt is None or not category


AI_SYS = """Sei il modulo di estrazione del Content Intelligence Hub per la promozione turistica pubblica dell'Abruzzo.
Ricevi il testo grezzo di un AVVISO o COMUNICATO di un ente pubblico, estratto da un PDF (può contenere rumore di impaginazione).
Estrai i metadati editoriali del documento.
Regole ferree:
- NON inventare nulla: se un dato non è nel testo, lascia la stringa vuota.
- La data è quella dell'evento o dell'avviso, in formato ISO YYYY-MM-DD.
- Il titolo è breve e informativo (max 15 parole), senza numeri di protocollo.
Rispondi SOLO con JSON valido, senza testo aggiuntivo:
{"title":"titolo breve","date":"YYYY-MM-DD","category":"una tra: natura, agroalimentare, borghi, cammini, identita, eventi, costa, trasporti","summary":"riassunto in 2 frasi"}"""


def build_user_prompt(text: str, limit: int = 4000) -> str:
    """Prompt utente: il testo del PDF, troncato per non far esplodere i token."""
    return f"TESTO DELL'AVVISO:\n{text[:limit]}"


def merge_ai(parsed: dict | None, title: str, dt: datetime | None,
             category: str) -> tuple[str, datetime | None, str, str]:
    """Fonde la risposta del modello con l'euristica: l'AI **riempie i buchi**, non
    sovrascrive ciò che le regole hanno già determinato (così un PDF ben formato dà
    sempre lo stesso risultato). Ritorna (title, dt, category, summary)."""
    if not parsed:
        return title, dt, category, ""
    title = title or (parsed.get("title") or "").strip()
    category = category or (parsed.get("category") or "").strip().lower()
    if dt is None:
        raw = (parsed.get("date") or "").strip()
        try:
            dt = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            dt = None
    return title, dt, category, (parsed.get("summary") or "").strip()
