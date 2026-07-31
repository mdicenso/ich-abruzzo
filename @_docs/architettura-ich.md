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

### 7.1 Backend pluggable — JSON locale **o** Postgres/Neon (2026-07-23)

Il disco di Streamlit Cloud è **effimero**: i file JSON versionati bastano finché
lo stato lo scrivono i commit, ma lo stato prodotto *runtime* (item processati,
pubblicazioni, audit, query) si azzererebbe ad ogni redeploy. Soluzione adottata:
lo store è **pluggable**, stessa interfaccia pubblica, backend scelto in automatico:

- **JSON locale** (default) — file sopra, sviluppo offline, nessuna dipendenza.
- **Postgres / Neon** — attivo quando è impostata `ICH_DATABASE_URL` (env o
  `st.secrets`). Stato **durevole cross-redeploy**. Codice: `ich/store_pg.py`
  (psycopg3; `prepare_threshold=None` per il pooler Neon). Tabelle: `items`,
  `outbox`, `audit`, `queries`, `feed_sources`, `topics`.

**Progetto Neon dedicato** (`ich-abruzzo`, region Frankfurt), **separato** dal
progetto `cdp-crm` del CDP: stesso account/vendor (nessuna frammentazione), ma DB
isolato → **espianto pulito** (`pg_dump` dell'intero progetto). Se il DB non è
raggiungibile lo store **degrada al JSON** senza mai sollevare (app sempre viva).

Vie d'espianto/migrazione (in `ich/store.py`, esposte nella pagina «Gestione dati»):
`export_to_json()` (backend → file, backup) e `import_from_json()` (file → backend,
migrazione una-tantum, idempotente).

Le **fonti del Serbatoio 2** (`sources_config.json`) seguono lo stesso principio:
`ich/feeds.py` le rende durevoli (tabella `feed_sources`, seminata dal JSON) e
gestibili dalla UI (aggiungi URL+descrizione, abilita/disabilita, elimina) — vedi §12.

Anche gli **argomenti editoriali** (`ich/topics.py`, tab «Argomenti») usano lo stesso
schema pluggable: tabella `topics` seminata dal JSON al primo uso → le modifiche fatte
in UI persistono ai redeploy. `export_to_json()` include ora anche gli argomenti.

L'alternativa "commit+push come lo scheduler TDH" resta il piano B (più fragile: il
push ri-triggera il redeploy, rumore di commit) — vedi §11.

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

- **Store**: ~~JSON versionati vs store esterno~~ → **DECISO (2026-07-23): backend
  pluggable JSON/Postgres, store esterno = Neon dedicato** (§7.1). Piano B (commit+push
  stile scheduler TDH) accantonato.
- **Set canali iniziale**: si tengono i 5 attuali? Se ne aggiunge subito uno
  (es. `trasporti`) o restano 5 finché B non è solido?
- **`id` deterministico**: schema di derivazione (hash di fonte+data+titolo?) per
  abilitare il dedup reale (oggi il check "duplicato" è sempre `pass`).

## 12. Pagina «Gestione dati» (Serbatoio 2 + persistenza)

Come la pagina *Gestione Dati* del TDH: rende visibile e governabile ciò che il
motore legge e dove salva.

- **Stato persistenza**: mostra il backend attivo (JSON locale / Postgres Neon) e i
  pulsanti *Esporta su JSON* (espianto) e *Importa JSON→DB* (migrazione una-tantum).
- **Fonti del feed** (Tabella 1): elenco fonti con abilita/disabilita ed elimina;
  form *Aggiungi fonte* (URL + descrizione + connettore feed/json/ical/pdf + tipo + icona).
  La modifica è durevole (DB o JSON) senza redeploy. **Fonti reali verificate
  attive**: ANSA Abruzzo e **Regione Abruzzo** (feed ufficiale del portale). Nota
  di robustezza: molti feed della PA italiana girano su **Drupal** e antepongono
  commenti *THEME DEBUG* prima di `<?xml` → il connettore `feed` ripulisce il
  preambolo (`_xml_bytes`) prima del parse, così questi feed non falliscono.
  Secondo problema tipico della PA: **catena TLS incompleta** (il server non
  invia il certificato intermedio) → in cloud (Linux/certifi) `SSLError`. Es.
  `regione.abruzzo.it` omette l'intermedio Sectigo R36. Fix: i connettori usano
  un CA bundle unito **certifi + `data/certs/pa_intermediates.pem`**
  (`_verify_bundle`) che completa la catena **senza disabilitare la verifica**;
  per un nuovo feed che fallisce così si aggiunge l'intermedio a quel PEM.
- **Prova l'ingestione** (Tabella 2): lancia `fetch_live` e mostra cosa arriva e
  quali fonti falliscono, senza scrivere nulla.

Codice: `ich/feeds.py` (gestione fonti, backend-agnostica) + `page_gestione_dati()`
in `app.py`, gruppo di navigazione «Sistema».

### 12.1 Connettore PDF (`kind="pdf"`) — il primo con AI in ingestione

La ricognizione dei feed (29-07-2026, vedi `@_docs/fonti-dati-ich.md`) ha mostrato
che l'ecosistema abruzzese pubblica pochissimo in RSS: **gli avvisi vivono come
PDF**. Il bando li ammette esplicitamente («.pdf nativo, non scansioni»), quindi
questo connettore apre una classe di fonti altrimenti irraggiungibile.

**Un documento = un item.** Un avviso è un atto singolo, non un elenco; scoprire
*molti* PDF linkati da una pagina sarà compito del futuro connettore sitemap/HTML.

**Perché euristiche prima e AI dopo.** Gli atti della PA hanno un impianto molto
regolare (`COMUNE DI …`, `OGGETTO: …`, `Prot. n. … del …`), quindi nella maggior
parte dei casi i metadati si ricavano con regole deterministiche: gratis,
ripetibili, verificabili. Il modello interviene **solo sui campi rimasti vuoti**
(`needs_ai`) e **non sovrascrive** ciò che le regole hanno già risolto → un PDF
ben formato non consuma token e dà sempre lo stesso risultato. L'item porta
`ai_assisted: true/false` per tracciabilità.

Scelte di dettaglio, tutte coperte da `tools/smoke_pdf.py`:
- **titolo**: coda della riga `OGGETTO:`/`AVVISO:`/`BANDO:` (o la riga seguente se
  l'etichetta è isolata); in mancanza, la prima riga di sostanza **saltando le
  intestazioni** — non solo l'ente (`COMUNE DI…`) ma anche l'ufficio che firma
  (`Dipartimento`, `Settore`, `Servizio`…), che altrimenti diventerebbe il titolo;
- **data**: si preferisce la forma **estesa** ("14 agosto 2026") alla numerica,
  perché la prima è quasi sempre la data dell'*evento* nel corpo, la seconda il
  protocollo in intestazione. Le date impossibili (31/02) vengono scartate;
- **categoria**: tassonomia editoriale per **radici ancorate a inizio parola**.
  Il confronto per sottostringa era una trappola: `orso` matchava dentro
  `percorso`, classificando come *natura* qualunque testo con quella parola;
- **scansioni**: PDF senza testo estraibile → `ValueError` esplicito (serve OCR).

**Purezza del package.** Come `generate.py`, `ich/pdfdoc.py` non importa né
Anthropic né Streamlit: `app.py` inietta la chiamata al modello con
`sources.set_ai_extractor()`. Senza registrazione (o senza API key) l'ingestione
prosegue in sola euristica, e un errore del modello non la fa fallire.
