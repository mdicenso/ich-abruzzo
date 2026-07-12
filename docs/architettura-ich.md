# ICH — Architettura del motore (ingestione → normalizzazione → dispatch)

> Documento di design. Definisce il "da grande" di ICH prima dell'implementazione.
> Da leggere insieme a `fonti-dati-ich.md` (le fonti) e al `README`.

## 1. Visione (identità bloccata)

ICH è **un motore che raccoglie informazioni eterogenee** (eventi, sagre, avvisi,
info trasporti, news territoriali…), **le analizza e normalizza**, e **le dispatcha
verso più canali** dopo una validazione di conformità e un'approvazione umana.

```
        INGESTIONE            NORMALIZZAZIONE               DISPATCH
   (fonti disparate)   →   (analisi + guardrail +   →   (N canali plugin)
                            schema canonico unico)
```

Il **chatbot è uno dei canali di uscita** (canale *pull*), non il protagonista.
Il protagonista è il motore: *un contenuto istituzionale verificato, distribuito
in modo conforme e tracciabile su N canali.*

## 2. I quattro principi architetturali

1. **Schema canonico unico (`CanonicalItem`).** Esiste UNA sola forma normalizzata
   del contenuto. L'ingestione converte *verso* di essa; il dispatch converte *da*
   essa. Nessun canale conosce le fonti; nessuna fonte conosce i canali.
2. **Sorgenti e canali sono plugin.** Aggiungere una fonte o un canale = aggiungere
   un modulo che rispetta un'interfaccia, **senza toccare il motore**.
3. **Human-in-the-loop + audit.** Niente raggiunge un canale senza (a) superare il
   Guardrail e (b) approvazione umana. Ogni decisione è tracciata (EU AI Act).
4. **Stato versionato nel repo.** Disco Streamlit Cloud effimero → gli store sono
   file JSON versionati nel repo (stesso metodo di TDH). Confine netto per poter
   in futuro passare a DB/store esterno senza riscrivere il motore.

## 3. Le fasi del motore (data-flow)

```
┌──────────────┐   RawItem    ┌─────────────────────────────────────┐
│  INGESTIONE  │ ───────────▶ │           NORMALIZZAZIONE           │
│  connettori  │              │  1. Analisi AI (topic/entità/lingue)│
│  (plugin)    │              │  2. Guardrail (6 check conformità)  │
│  RSS·seed·   │              │  3. Mapping → CanonicalItem         │
│  sitemap·API │              └───────────────┬─────────────────────┘
└──────────────┘                              │ CanonicalItem
                                              ▼
                                   ┌─────────────────────┐
                                   │  GATE DI APPROVAZIONE│  ◀── operatore umano
                                   │  (blocked mai passa) │      (obbligatorio)
                                   └──────────┬──────────┘
                                              │ item approvato
                                              ▼
                          ┌───────────────────────────────────────┐
                          │              DISPATCH                  │
                          │  per ogni canale abilitato nel REGISTRO│
                          │  ┌─────────┐   ┌──────┐                │
                          │  │RENDERER │─▶ │ SINK │─▶ destinazione │
                          │  └─────────┘   └──────┘                │
                          └───────────────────────────────────────┘
        canali: 💬 chatbot(pull) · 📱 mobile · 📺 signage · 🖥️ tv · ⚡ api-feed

              ┌──────────────────────────────────────────┐
              │  STORE (JSON versionati): items · publish │  ── audit log
              └──────────────────────────────────────────┘
                                   ▲
                                   │ legge tutti gli store
                          ┌────────┴─────────┐
                          │ INTELLIGENCE (C) │  gap · domanda · stagionalità
                          └──────────────────┘
```

## 4. Lo schema canonico (`CanonicalItem`) — la chiave di volta

L'unico contratto che tutto il sistema condivide. Bozza dei campi:

```jsonc
{
  "id": "evt_2026_0731_perdonanza",     // stabile, deterministico
  "provenance": {                        // da dove viene, per audit e dedup
    "source_id": "abruzzoturismo-rss",
    "source_kind": "rss",                // rss|sitemap|opendata|pdf|manual|api
    "url": "https://...",
    "ingested_at": "2026-07-12T10:00:00Z"
  },
  "type": "EVENTO",                      // EVENTO|NEWS|AVVISO|TRASPORTI|SAGRA
  "title": "…",
  "body": "…",                           // testo normalizzato, pulito
  "category": ["borghi", "identita"],    // tassonomia bando (vedi §5)
  "entities": { "luoghi": [], "date": [], "eventi": [] },
  "when": { "start": "2026-07-31", "end": "2026-08-02" },  // parsed, non testo
  "where": { "comune": "L'Aquila", "prov": "AQ", "geo": null },
  "languages": ["IT", "EN"],
  "importance": 8,
  "governance": {
    "guardrail": "pass|warn|blocked",
    "guardrail_detail": { /* i 6 check */ },
    "approval": "pending|approved|rejected",
    "approved_by": null, "approved_at": null
  }
}
```

> Regola: **tutto ciò che oggi in `app.py` è ad-hoc** (`item['raw']`, `item['type']`,
> l'output di `ANALYSIS_PROMPT`, l'esito del guardrail) confluisce qui, in un solo
> oggetto con un solo posto per ogni informazione.

## 5. Tassonomia (dal bando, riuso)

`natura · agroalimentare · borghi · cammini · identita · eventi · costa · trasporti`
— enum chiuso in `category`. Serve al guardrail, al routing e all'Intelligence (C).

## 6. Il registro dei canali (dispatch as plugin)

Ogni canale è una voce dichiarativa + due funzioni:

```python
# channels/registry.py
CHANNELS = [
  Channel(id="chatbot", label="Assistente", kind="pull",
          renderer=render_chatbot, sink=sink_kb),        # alimenta la KB
  Channel(id="api",     label="Feed API",  kind="push",
          renderer=render_api,     sink=sink_feed_json),  # data/published/feed.json
  Channel(id="mobile",  label="Mobile",    kind="push",
          renderer=render_mobile,  sink=sink_stub),
  Channel(id="signage", label="Signage",   kind="push",
          renderer=render_signage, sink=sink_stub),
  Channel(id="tv",      label="TV Panel",  kind="push",
          renderer=render_tv,      sink=sink_stub),
]
```

- **renderer**: `CanonicalItem → payload` del canale (formato/lunghezze/stile).
  Sostituisce l'attuale `REWRITE_PROMPT` monolitico: un renderer per canale.
- **sink**: `payload → destinazione`. `sink_feed_json` scrive un file versionato;
  `sink_kb` inserisce nella KB del chatbot; `sink_stub` per ora logga soltanto.
- Aggiungere un canale = una `Channel(...)` in più. Il motore non cambia.

**Separazione chiave:** *renderer* = "che aspetto ha", *sink* = "dove va". Distinte.

## 7. Persistenza (store versionati)

| Store | File | Contenuto |
|---|---|---|
| Items normalizzati | `data/store/items.json` | i `CanonicalItem` in stato `pending/approved` |
| Pubblicati (feed API) | `data/published/feed.json` | uscita reale, consumabile da Abruzzo Wild |
| Audit log | `data/store/audit.jsonl` | ogni decisione, append-only, EU AI Act |

Oggi tutto vive in `st.session_state` (volatile). Il passaggio a questi file è ciò
che trasforma il PoC in motore reale. Aggiornamento remoto: lo stesso schema del
**scheduler TDH** (task Windows → commit+push) può rigenerare/pubblicare.

## 8. Intelligence Layer (C) — come si aggancia

C **non** è un pezzo nuovo del flusso: è un *lettore* degli store che B produce.

- **Content gap**: query dell'assistente senza risposta → backlog "da produrre"
  (embrione già in `intelligence.gaps_from_log`).
- **Domanda/stagionalità**: Google Trends + ISTAT (riuso TDH) → *quali* topic
  spingere e *quando* (neve d'inverno, trabocchi d'estate) → priorità in ingestione.
- **Consumo**: cosa è stato dispacciato vs consumato → feedback sul valore.

Dipendenza: **C richiede che B persista i dati** (§7). Per questo B viene prima.

## 9. Mappa: codice attuale → moduli target

| Oggi | Diventa | Nota |
|---|---|---|
| `ich/sources.py` (RSS+seed) | `ich/ingest/` (connettori plugin) | RSS è il primo connettore |
| `ANALYSIS_PROMPT` + guardrail in `app.py` | `ich/pipeline/` | analisi, guardrail, mapping→canonico |
| `REWRITE_PROMPT` + `channel_fallback` | `ich/channels/` | registro + un renderer per canale |
| `st.session_state.published` | `ich/dispatch/` + `data/published/` | sink reali, persistenza |
| `ich/kb.py` | canale `chatbot` (sink_kb) | resta, ma come destinazione del dispatch |
| `ich/intelligence.py` | layer C | legge gli store |
| `app.py` | solo UI | orchestra i moduli, non contiene la logica |

## 10. Ordine di implementazione (incrementale, ogni passo lascia l'app viva)

1. **Schema canonico + store** (`CanonicalItem`, `data/store/…`, load/save). Fondamenta.
2. **Canale API reale** (`render_api` + `sink_feed_json` → `data/published/feed.json`
   persistente). Primo dispatch vero; ponte verso Abruzzo Wild.
3. **Registro canali** (estrai i 5 canali dal prompt monolitico a renderer separati).
4. **Persistenza pipeline** (approvazione scrive negli store, non in session_state).
5. **Connettori come plugin** (generalizza `sources.py`; aggiungi 1 fonte nuova).
6. **Aggancio C** (gap + stagionalità che leggono gli store).

## 11. Decisioni aperte (da confermare)

- **Store**: JSON versionati nel repo (proposto, coerente con TDH) vs store esterno.
- **Set canali iniziale**: si tengono i 5 attuali? Se ne aggiunge subito uno
  (es. `trasporti`) o restano 5 finché B non è solido?
- **`id` deterministico**: schema di derivazione (hash di fonte+data+titolo?) per
  abilitare il dedup reale (oggi il check "duplicato" è sempre `pass`).
