"""Smoke test del connettore PDF (`kind="pdf"`) — pypdf + stdlib, niente Streamlit.

Verifica le EURISTICHE di `ich/pdfdoc.py` (titolo, data, categoria, tipo) e il
comportamento del fallback AI iniettato: che venga chiamato **solo** quando
restano buchi, che non sovrascriva ciò che le regole hanno già stabilito, e che
un suo errore non faccia fallire l'ingestione.

I PDF di prova sono fabbricati qui a runtime (PDF 1.4 nativi minimi, scritti a
mano): niente binari opachi nel repo e i casi limite restano leggibili.

Lancio (dalla radice del repo):
    C:\\Users\\mcenso\\tdh_venv\\Scripts\\python.exe tools/smoke_pdf.py
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ich import pdfdoc, sources  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {label}")
    else:
        fail += 1
        print(f"  [FAIL] {label} {extra}")


# ─── generatore di PDF nativi minimi (nessuna dipendenza) ────────────────────
def make_pdf(lines, title=None):
    """PDF 1.4 valido con un blocco di testo. Serve a fabbricare i casi di prova
    senza committare binari opachi."""
    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content = "BT /F1 11 Tf 50 800 Td 15 TL\n"
    for ln in lines:
        content += f"({esc(ln)}) Tj T*\n"
    content += "ET"
    cb = content.encode("cp1252", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(cb)).encode() + b" >>\nstream\n" + cb + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    if title:
        objs.append(b"<< /Title (" + esc(title).encode("cp1252", "replace") + b") >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {n} /Root 1 0 R"
    if title:
        trailer += f" /Info {len(objs)} 0 R"
    out += (trailer + " >>\nstartxref\n" + str(xref) + "\n%%EOF\n").encode()
    return bytes(out)


# I PDF di prova finiscono in una cartella temporanea: il repo resta pulito.
TMP = Path(tempfile.mkdtemp(prefix="ich-smoke-pdf-"))

print("\n1) Avviso classico con OGGETTO + data numerica")
pdf1 = make_pdf([
    "COMUNE DI CIVITELLA DEL TRONTO",
    "Provincia di Teramo",
    "Prot. n. 4821 del 03/08/2026",
    "OGGETTO: Sagra degli Arrosticini 2026 - programma e viabilita'",
    "Si comunica che dal 12 agosto 2026 si svolgera' la Sagra degli",
    "Arrosticini nel centro storico del borgo. Prodotti tipici locali,",
    "musica popolare e mercatino dell'artigianato.",
])
p1 = TMP / "t1.pdf"
p1.write_bytes(pdf1)
txt = pdfdoc.extract_text(pdf1)
check("testo estratto", "Sagra degli Arrosticini" in txt)
t = pdfdoc.guess_title(txt)
check("titolo dalla riga OGGETTO", t.startswith("Sagra degli Arrosticini"), f"-> {t!r}")
check("titolo senza numero di protocollo", "4821" not in t, f"-> {t!r}")
d = pdfdoc.guess_date(txt)
check("data estesa preferita (12 agosto 2026)", d == datetime(2026, 8, 12), f"-> {d}")
c = pdfdoc.guess_category(txt)
check("categoria dedotta", c in ("eventi", "agroalimentare"), f"-> {c!r}")
check("tipo EVENTO", pdfdoc.guess_type(txt) == "EVENTO")
check("needs_ai False (euristica completa)", pdfdoc.needs_ai(t, d, c) is False)

print("\n2) Connettore end-to-end da file locale")
items = sources.fetch_source({"kind": "pdf", "path": str(p1), "name": "Avviso test",
                              "source": "Comune di Civitella"}, max_items=5)
check("un documento = un item", len(items) == 1, f"-> {len(items)}")
it = items[0]
check("source_kind=pdf", it["source_kind"] == "pdf")
check("pubdate_iso valorizzato", it["pubdate_iso"].startswith("2026-08-12"), f"-> {it['pubdate_iso']}")
check("category propagata", it["category"] and it["category"][0], f"-> {it['category']}")
check("ai_assisted False senza extractor", it["ai_assisted"] is False)
check("icona di default", it["icon"] == "📄")

print("\n3) OGGETTO su riga isolata -> titolo dalla riga seguente")
pdf3 = make_pdf([
    "COMUNE DI SCANNO", "OGGETTO:",
    "Riapertura del sentiero del Lago di Scanno dopo i lavori",
    "I lavori si sono conclusi il 5 settembre 2026.",
])
t3 = pdfdoc.guess_title(pdfdoc.extract_text(pdf3))
check("titolo preso dalla riga dopo", t3.startswith("Riapertura del sentiero"), f"-> {t3!r}")

print("\n4) Nessun OGGETTO -> prima riga di sostanza, saltando le intestazioni")
pdf4 = make_pdf([
    "REGIONE ABRUZZO", "Dipartimento Turismo", "www.regione.abruzzo.it",
    "Al via il cammino dei tratturi tra Abruzzo e Molise",
    "Il percorso collega la transumanza storica.",
])
t4 = pdfdoc.guess_title(pdfdoc.extract_text(pdf4))
check("intestazioni ente saltate", t4.startswith("Al via il cammino"), f"-> {t4!r}")
check("categoria cammini", pdfdoc.guess_category(pdfdoc.extract_text(pdf4)) == "cammini")

print("\n5) Data non valida (31/02) -> scartata, si passa alla successiva")
pdf5 = make_pdf(["OGGETTO: Avviso di prova", "Data errata 31/02/2026 poi 04/03/2026."])
d5 = pdfdoc.guess_date(pdfdoc.extract_text(pdf5))
check("31/02 scartata, presa 04/03", d5 == datetime(2026, 3, 4), f"-> {d5}")

print("\n6) PDF-scansione (nessun testo) -> errore parlante")
scan = make_pdf([])   # nessun testo nel content stream
try:
    pdfdoc.extract_text(scan)
    check("solleva ValueError", False)
except ValueError as e:
    check("solleva ValueError con messaggio su OCR", "scansione" in str(e).lower())
except Exception as e:
    check("solleva ValueError", False, f"-> {type(e).__name__}")

print("\n7) Metadati: titolo-spazzatura di Word scartato")
check("Microsoft Word - x.doc scartato",
      pdfdoc.meta_title(make_pdf(["ciao"], title="Microsoft Word - avviso.doc")) == "")
check("titolo metadati buono tenuto",
      pdfdoc.meta_title(make_pdf(["ciao"], title="Avviso viabilita' agosto 2026"))
      .startswith("Avviso viabilita"))

print("\n8) Fallback AI: iniettato, chiamato SOLO se restano buchi")
calls = []


def fake_ai(system, user):
    calls.append(user)
    return {"title": "Titolo dal modello", "date": "2026-09-01",
            "category": "borghi", "summary": "Riassunto AI."}


sources.set_ai_extractor(fake_ai)
# 8a: PDF completo -> l'AI NON deve essere chiamata
sources.fetch_source({"kind": "pdf", "path": str(p1), "name": "x"})
check("nessuna chiamata AI quando l'euristica basta", len(calls) == 0, f"-> {len(calls)}")

# 8b: PDF povero (niente data, niente categoria) -> l'AI riempie i buchi
poor = make_pdf(["OGGETTO: Comunicazione della segreteria", "Testo generico."])
pp = TMP / "t8.pdf"
pp.write_bytes(poor)
it8 = sources.fetch_source({"kind": "pdf", "path": str(pp), "name": "y"})[0]
check("AI chiamata quando ci sono buchi", len(calls) == 1, f"-> {len(calls)}")
check("ai_assisted True", it8["ai_assisted"] is True)
check("data presa dall'AI", it8["pubdate_iso"].startswith("2026-09-01"), f"-> {it8['pubdate_iso']}")
check("categoria presa dall'AI", it8["category"] == ["borghi"], f"-> {it8['category']}")
check("titolo euristico NON sovrascritto dall'AI",
      it8["title"].startswith("Comunicazione della segreteria"), f"-> {it8['title']!r}")
check("summary AI usato come corpo", it8["raw"] == "Riassunto AI.", f"-> {it8['raw']!r}")

# 8c: AI che esplode -> l'ingestione continua in sola euristica
def boom(system, user):
    raise RuntimeError("modello non raggiungibile")


sources.set_ai_extractor(boom)
it8c = sources.fetch_source({"kind": "pdf", "path": str(pp), "name": "z"})[0]
check("errore AI non fa fallire l'ingestione", it8c["title"] != "")
sources.set_ai_extractor(None)

print("\n9) Registro connettori")
check("kind 'pdf' registrato", sources.CONNECTORS.get("pdf") is not None)
check("alias 'avviso' -> stesso connettore",
      sources.CONNECTORS.get("avviso") is sources.CONNECTORS.get("pdf"))
check("connettori preesistenti intatti",
      all(k in sources.CONNECTORS for k in ("rss", "atom", "feed", "json", "rest", "api", "ical")))

print(f"\n{'=' * 55}\nOK={ok}  FAIL={fail}")
sys.exit(1 if fail else 0)
