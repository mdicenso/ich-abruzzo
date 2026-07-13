# ICH — Content Intelligence Hub (Abruzzo)

Assistente Virtuale Turistico + hub di governo dei contenuti per la promozione
turistica pubblica dell'Abruzzo. App **Streamlit** (file `app.py`), online su
Streamlit Community Cloud. Nasce dal modello del bando GAL Valle Umbra e Sibillini
(vedi `docs/`), adattato all'Abruzzo.

## Cosa fa (tab dell'app)

1. **🔄 Pipeline E2E** — un contenuto istituzionale passa per: Analisi AI →
   Guardrail (6 check di conformità) → Rewriting (5 canali) → Validazione umana →
   Pubblicazione. Riproduce il principio del bando: contenuti pubblicati solo
   "previa verifica e assunzione di responsabilità".
2. **📡 Output Canali** — i contenuti approvati, declinati per chatbot, mobile,
   signage, TV, API. **Ogni canale** ha uno sbocco reale: l'approvazione scrive un
   *outbox* JSON **persistente e versionato** in `data/published/<canale>.json`, che
   sopravvive al reload. L'API usa `feed.json` (consumabile da Abruzzo Wild); il
   canale *chatbot* (pull) alimenta l'assistente.
3. **💬 Assistente** — chatbot territoriale che risponde **sul knowledge base**
   (vedi sotto) citando le fonti, senza promuovere marchi commerciali.
4. **📊 Intelligence** — analytics sulla domanda turistica.
5. **📋 Audit** — registro decisioni **durevole** (`data/store/audit.jsonl`): ogni
   evento della pipeline (blocked, guardrail OK, pubblicato, rifiutato) è tracciato
   con timestamp, attore e contenuto (trasparenza EU AI Act), non più solo in sessione.

## API key

L'app gira **anche senza API key** (modalità demo con fallback). Le funzioni AI
si attivano quando l'utente inserisce la **propria** key Anthropic nel riquadro
«🔑 Assistente AI» in alto → non consuma i crediti dell'autore. La key resta solo
nella sessione. In alternativa si può impostare il secret `ANTHROPIC_KEY`.

## Struttura

```
app.py                       # UI Streamlit e orchestrazione
ich/
  model.py                   # schema canonico dell'item (CanonicalItem) + id deterministico
  store.py                   # persistenza versionata: items / outbox canali / audit
  channels.py                # registro canali: renderer + sink per plugin (5 canali)
  dispatch.py                # Step 6 — dispatch reale guidato dal registro canali
  kb.py                      # Serbatoio 1 — knowledge base territoriale (retrieval RAG-lite)
  sources.py                 # Serbatoio 2 — flusso eventi & news (seed + ingestione RSS)
  intelligence.py            # Serbatoio 3 — destination & demand intelligence
data/
  kb/abruzzo_kb.json         # base conoscitiva curata (versionata: regge il disco effimero del cloud)
  feed/events_seed.json      # seed del flusso contenuti + casi di test del Guardrail
  feed/sources_config.json   # elenco dei feed RSS reali da ingerire
  intelligence/abruzzo_destination.json  # snapshot dati reali ISTAT/BdI (dal TDH)
  store/items.json           # store dei CanonicalItem normalizzati (pending/approved)
  store/audit.jsonl          # log append-only delle decisioni (EU AI Act)
  published/<canale>.json    # outbox durevoli del dispatch (feed=API, + chatbot/mobile/signage/tv)
tools/
  build_intelligence_snapshot.py  # rigenera lo snapshot dalla cache del TDH
docs/
  fonti-dati-ich.md          # roadmap delle fonti dati (3 serbatoi)
  architettura-ich.md        # architettura del motore (ingestione → normalizzazione → dispatch)
requirements.txt
DEPLOY.md                    # istruzioni di deploy su Streamlit Cloud
```

I "3 serbatoi" di dati (vedi `docs/fonti-dati-ich.md`):
- **1 · Knowledge base territoriale** — statico, curato → alimenta l'assistente. ✅ attivo
- **2 · Flusso eventi & news** — dinamico → alimenta la pipeline. ✅ attivo (seed + RSS live)
- **3 · Intelligence/domanda** — riusa i dati del progetto TDH. ✅ attivo

### Il motore: ingestione → normalizzazione → dispatch

Oltre ai 3 serbatoi, ICH è un **motore che raccoglie informazioni eterogenee, le
normalizza e le dispatcha su più canali** (il chatbot è uno dei canali di uscita).
Progetto architetturale completo in `docs/architettura-ich.md`. Fondamenta già posate:

- **Schema canonico** (`ich/model.py`) — un unico `CanonicalItem` su cui tutto si
  accorda: l'ingestione converte le fonti *verso* di esso, il dispatch converte *da*
  esso verso i canali. `id` deterministico (hash fonte+data+titolo) → dedup reale.
- **Store versionati** (`ich/store.py`) — items, feed pubblicato e audit come file
  JSON nel repo (il disco Streamlit Cloud è effimero).
- **Registro canali** (`ich/channels.py`) — i 5 canali sono plugin: ognuno ha un
  *renderer* (dà forma al contenuto, con fallback deterministico senza API key) e un
  *sink* (scrive l'outbox durevole in `data/published/`). Aggiungere un canale = una
  voce nel registro, senza toccare il motore.
- **Dispatch reale** (`ich/dispatch.py`) — all'approvazione itera sul registro:
  ogni canale rende il suo payload e lo persiste nel proprio outbox. Un canale che
  fallisce non blocca gli altri (annotato nell'audit).
- **Ledger + audit durevoli** — ogni item che entra in pipeline è salvato in
  `items.json` col suo stato (pending → approved/rejected) ed esito guardrail, e
  ogni decisione è scritta nell'audit `audit.jsonl`. La UI legge da questi store,
  non più da variabili di sessione: lo stato sopravvive al reload ed è la base che
  alimenterà l'Intelligence (C).

### Destination & Demand Intelligence (Serbatoio 3)

Il tab Intelligence usa **dati reali**, non più inventati:
- *Destination* (macro): presenze ISTAT, posti letto, spesa turisti esteri (Banca
  d'Italia), estratti dalla cache del progetto **TDH** e congelati in
  `data/intelligence/abruzzo_destination.json` (rigenerabile con
  `tools/build_intelligence_snapshot.py`). Mostra stagionalità e recupero post-Covid.
- *Demand* (micro): le **domande reali** poste all'Assistente vengono registrate e
  aggregate in topic richiesti e **content gap** (domande a cui il KB non sa
  rispondere → contenuti prioritari da aggiungere, come previsto dal bando).

### Flusso eventi & news (Serbatoio 2)

La coda della pipeline unisce un *seed* versionato (`data/feed/events_seed.json`,
con i due casi di test del Guardrail) e contenuti **live** ingeriti da fonti RSS
reali elencate in `data/feed/sources_config.json` (es. ANSA Abruzzo). Il pulsante
"🔄 Aggiorna fonti (RSS live)" nella Pipeline scarica i contenuti freschi (in
cache 15 min); `ich/sources.py` li normalizza nello schema degli item e li fa
passare per il Guardrail come tutti gli altri. Per aggiungere fonti basta inserire
nuovi feed nel file di config.

### Knowledge base (Serbatoio 1)

`data/kb/abruzzo_kb.json` contiene schede territoriali (enogastronomia, borghi,
natura, cammini, costa, cultura, fauna, esperienze), ognuna con `title`, `text`,
`source`, `tags`. `ich/kb.py` fa un recupero leggero per parole-chiave (con
stemming e sinonimi italiani, niente vector DB) e inietta i chunk pertinenti nel
prompt dell'assistente, che cita le fonti. Per ampliare il KB basta aggiungere
voci al JSON (modello "ogni ente contribuisce contenuti", come nel bando).

## Avvio in locale

Porta **8502** (TDH usa la 8501). Vedi `@_scorciatoie/COMANDI.txt`.
```
C:\Users\mcenso\tdh_venv\Scripts\streamlit run app.py
```
La porta locale è fissata in `.streamlit/config.toml` (non versionato: in cloud
Streamlit usa la sua 8501).

## Deploy

Ogni `git push` su `main` ridistribuisce l'app su Streamlit Cloud. Dettagli in
`DEPLOY.md`.
