# Deploy di ICH su Streamlit Community Cloud

ICH (Content Intelligence Hub — Abruzzo) è un'app Streamlit a file unico
(`app.py`). `requirements.txt` elenca le dipendenze. L'app gira **anche senza
API key**: le funzioni AI (analisi, guardrail reale, rewriting, assistente) si
attivano quando l'utente inserisce la propria key nel riquadro «🔑 Assistente AI»
in alto → non consuma i crediti dell'autore.

In locale gira sulla porta 8502 (TDH usa la 8501); in cloud la porta non conta.

## 1 — Pubblica il codice su GitHub

**Opzione A — GitHub Desktop (consigliata, senza comandi)**
1. Apri GitHub Desktop → *File ▸ Add local repository* → scegli la cartella `Progetto_ICH`.
2. *Publish repository* → spunta **Keep this code private** → *Publish*.

**Opzione B — da terminale** (incolla nel prompt di Claude Code col prefisso `!`)
1. Crea un repo **vuoto e privato** su https://github.com/new (es. `ich-abruzzo`),
   senza README/licenza.
2. Poi, dentro la cartella di ICH:
   ```
   git remote add origin https://github.com/<tuo-utente>/ich-abruzzo.git
   git push -u origin main
   ```
   (al primo push si apre il browser per autorizzare GitHub.)

## 2 — Crea l'app su Streamlit Cloud

1. Vai su https://share.streamlit.io → *Create app* → *Deploy a public app from GitHub*.
2. Repository: il repo appena pubblicato · Branch: `main` · Main file: `app.py`.
3. *Deploy*. Il primo avvio installa le dipendenze (qualche minuto).

## 3 — Accesso e API key

- **API key:** ogni utente incolla la **propria** key Anthropic nel riquadro
  «🔑 Assistente AI». Resta solo nella sua sessione, non viene salvata nel repo.
  Senza key, tutta la parte dimostrativa (pipeline, canali, audit, analytics)
  funziona lo stesso con i contenuti di fallback.
- **Limitare l'accesso "su invito":** nel cruscotto dell'app **Settings ▸ Sharing**
  → imposta l'app come **privata** e aggiungi gli **indirizzi email** autorizzati.
- **(Opzionale) Key condivisa per il demo:** se vuoi che l'AI sia attiva per tutti
  senza far inserire la key, vai su **Settings ▸ Secrets** e incolla
  ```
  ANTHROPIC_KEY = "sk-ant-..."
  ```
  L'app la userà come default. Attenzione: così consuma i tuoi crediti.

## Note

- **Persistenza:** in cloud il disco è effimero; pubblicati, audit log e chat
  valgono per la sessione. (La persistenza su DB è un'evoluzione futura.)
- **Aggiornamenti:** ogni `git push` su `main` ridistribuisce l'app in automatico.
- **`cih-demo/`:** è il vecchio mockup React, tenuto solo come archivio. Su Streamlit
  Cloud viene ignorato (il main file è `app.py`).
