"""Sonda per scovare feed (RSS/Atom) sui siti istituzionali — Serbatoio 2.

Perche' esiste
--------------
Quasi nessuna PA abruzzese dichiara l'autodiscovery `<link rel="alternate">`:
i feed, quando ci sono, stanno a URL non standard (la Majella espone
`/rss_news.php`, trovato solo cercando `href=...rss` in TUTTO l'HTML). Questo
script automatizza quella caccia: per ogni sito identifica il CMS, raccoglie i
link candidati dall'HTML e tenta una lista di path noti, poi verifica che la
risposta sia **davvero** un feed XML (non una pagina di cortesia con 200).

⚠️ Da un PC dietro il proxy Indra, `curl` da' falsi `000` e talvolta `502`
(il proxy blocca il CONNECT): NON usarlo per concludere che un sito e' morto.
Il verificatore affidabile e' lo stack reale dell'app, che questo script usa:
`tdh_venv` + `truststore.inject_into_ssl()` + `requests` + il bundle CA con
gli intermedi PA (`ich.sources._verify_bundle`). In caso di dubbio, una
controprova indipendente dalla rete Indra si ottiene con un fetch lato server
(p.es. il tool WebFetch dell'assistente).

Uso
---
    C:\\Users\\mcenso\\tdh_venv\\Scripts\\python.exe tools/probe_sources.py https://sito1 https://sito2
"""
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    import truststore
    truststore.inject_into_ssl()
except Exception as e:  # pragma: no cover - dipende dall'ambiente
    print(f"[warn] truststore non iniettato: {e}")

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from ich.sources import _verify_bundle
    VERIFY = _verify_bundle() or True
except Exception as e:  # pragma: no cover
    print(f"[warn] bundle CA non disponibile: {e}")
    VERIFY = True

UA = {"User-Agent": "Mozilla/5.0 (compatible; ICH-Abruzzo/1.0; +content-intelligence-hub)"}

SIGNATURES = [
    ("Drupal",    re.compile(r"drupal|/sites/default/files", re.I)),
    ("WordPress", re.compile(r"wp-content|wp-includes", re.I)),
    ("Joomla",    re.compile(r"/media/jui/|joomla", re.I)),
    ("Halley",    re.compile(r"halleyweb|halley\.it", re.I)),
]

# path tentati a colpo sicuro: WordPress (/feed/, ?feed=rss2), Drupal Views
# (/rss.xml, <vista>.rss, /node/feed), Joomla (?format=feed), legacy PHP.
GUESSES = [
    "/feed/", "/feed", "/?feed=rss2", "/rss", "/rss.xml", "/atom.xml",
    "/rss_news.php", "/news/feed", "/notizie.rss", "/eventi.rss",
    "/node/feed", "/index.php?format=feed&type=rss",
]

HREF_FEED = re.compile(rb"""href\s*=\s*["']([^"']*(?:rss|feed|atom)[^"']*)["']""", re.I)


def _get(url):
    return requests.get(url, headers=UA, timeout=15, verify=VERIFY, allow_redirects=True)


def _is_feed(resp):
    """Vero se il corpo e' davvero un feed XML. Tollera i preamboli prima di
    `<?xml` (i Drupal PA con THEME DEBUG li antepongono: stessa insidia che
    `ich.sources._xml_bytes` gestisce in produzione)."""
    body = resp.content.lstrip()[:3000].lower()
    i = body.find(b"<?xml")
    if i > 0:
        body = body[i:]
    return b"<rss" in body or b"<feed" in body or b"<rdf" in body


def _count(resp):
    n = len(re.findall(rb"<item[\s>]", resp.content, re.I))
    return n or len(re.findall(rb"<entry[\s>]", resp.content, re.I))


def probe(site):
    site = site.rstrip("/")
    print(f"\n{'=' * 70}\n{site}")
    try:
        r = _get(site)
    except Exception as e:
        print(f"  HOME  [NO] {type(e).__name__}: {str(e)[:110]}")
        return []
    print(f"  HOME  {r.status_code}  server={r.headers.get('Server', '?')[:40]}")
    html = r.content.decode("utf-8", "ignore")
    cms = [n for n, rx in SIGNATURES if rx.search(html)]
    print(f"  CMS   {', '.join(cms) if cms else 'sconosciuto'}")

    cand = []
    for h in sorted({x.decode("utf-8", "ignore") for x in HREF_FEED.findall(r.content)}):
        cand.append(h if h.startswith("http") else
                    (site + h if h.startswith("/") else f"{site}/{h}"))
    if cand:
        print(f"  href  {len(cand)} candidati nell'HTML")
    cand += [site + g for g in GUESSES if site + g not in cand]

    hits = []
    for u in cand:
        try:
            rr = _get(u)
        except Exception:
            continue
        if rr.status_code == 200 and _is_feed(rr):
            n = _count(rr)
            # un feed valido ma VUOTO (o fermo da anni) non serve a nulla:
            # segnalalo, non e' una fonte utilizzabile.
            print(f"    [OK] FEED {u}  ({n} item)" + ("  <-- VUOTO" if not n else ""))
            hits.append((u, n))
    if not hits:
        print("    -- nessun feed trovato")
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for s in sys.argv[1:]:
        probe(s)
