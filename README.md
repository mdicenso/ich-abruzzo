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
   signage, TV, API.
3. **💬 Assistente** — chatbot territoriale che risponde **sul knowledge base**
   (vedi sotto) citando le fonti, senza promuovere marchi commerciali.
4. **📊 Intelligence** — analytics sulla domanda turistica.
5. **📋 Audit** — registro decisioni (trasparenza EU AI Act).

## API key

L'app gira **anche senza API key** (modalità demo con fallback). Le funzioni AI
si attivano quando l'utente inserisce la **propria** key Anthropic nel riquadro
«🔑 Assistente AI» in alto → non consuma i crediti dell'autore. La key resta solo
nella sessione. In alternativa si può impostare il secret `ANTHROPIC_KEY`.

## Struttura

```
app.py                     # UI Streamlit e orchestrazione
ich/
  kb.py                    # Serbatoio 1 — knowledge base territoriale (retrieval RAG-lite)
data/
  kb/abruzzo_kb.json       # base conoscitiva curata (versionata: regge il disco effimero del cloud)
docs/
  fonti-dati-ich.md        # roadmap delle fonti dati (3 serbatoi)
requirements.txt
DEPLOY.md                  # istruzioni di deploy su Streamlit Cloud
```

I "3 serbatoi" di dati (vedi `docs/fonti-dati-ich.md`):
- **1 · Knowledge base territoriale** — statico, curato → alimenta l'assistente. ✅ attivo
- **2 · Flusso eventi & news** — dinamico → alimenta la pipeline. 🚧 in costruzione
- **3 · Intelligence/domanda** — riusa i dati del progetto TDH. 🚧 da collegare

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
