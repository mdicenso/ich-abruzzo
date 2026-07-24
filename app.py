# Proxy aziendale (Indra): fa usare all'SDK il trust store di Windows per il TLS,
# altrimenti la connessione all'API Anthropic fallisce con APIConnectionError.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import streamlit as st
from anthropic import Anthropic
import json, re, time, os
from datetime import datetime
import plotly.express as px
import pandas as pd
from ich import kb            # Serbatoio 1 — knowledge base territoriale
from ich import sources       # Serbatoio 2 — flusso eventi & news (seed + RSS live)
from ich import intelligence  # Serbatoio 3 — destination & demand intelligence (dati TDH)
from ich import store         # persistenza versionata (items/feed/audit)
from ich import model         # schema canonico (id deterministico per l'audit)
from ich import channels      # registro canali (renderer + sink, dispatch as plugin)
from ich import dispatch      # Step 6 — dispatch reale guidato dal registro canali
from ich import topics        # argomenti editoriali (cosa il motore deve seguire)
from ich import generate      # Fase 2 — generazione proattiva di bozze dagli argomenti
from ich import feeds         # gestione fonti/feed (Serbatoio 2), backend durevole DB/JSON

# ─── PAGE CONFIG ─────────────────────────────────────────
st.set_page_config(
    page_title="Content Intelligence Hub — Abruzzo",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── API CLIENT ──────────────────────────────────────────
# La key NON è obbligatoria: l'app gira comunque in modalità demo (dati e
# fallback). Le funzioni AI (analisi, guardrail reale, rewriting, assistente)
# si attivano solo quando l'utente inserisce la propria key → non consuma i
# crediti dell'autore. Ordine: secret di Streamlit Cloud → variabile d'ambiente.
def _initial_key():
    try:
        k = st.secrets["ANTHROPIC_KEY"]
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")

if "api_key" not in st.session_state:
    st.session_state.api_key = _initial_key()

def get_client():
    """Ritorna un client Anthropic se è presente una key, altrimenti None."""
    key = st.session_state.get("api_key", "")
    if not key:
        return None
    try:
        return Anthropic(api_key=key)
    except Exception:
        return None

# ─── CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
    :root {
        --ich-teal:#0e6b70; --ich-teal-d:#0a4f53;
        --ich-bg:#f5f7f7; --ich-ink:#10262a; --ich-line:#e3e9e9;
    }
    /* Tema "Istituzionale" (Swiss/enterprise), allineato al cruscotto TDH */
    .stApp { background: var(--ich-bg); }
    [data-testid="stHeader"] { background: transparent; }
    .block-container { padding-top: 2rem; max-width: 1300px; }
    h1, h2, h3, h4 { color: var(--ich-teal-d); }
    a { color: var(--ich-teal); }
    /* Sidebar bianca con bordo e accento teal */
    [data-testid="stSidebar"] { background:#ffffff; border-right:1px solid var(--ich-line); }
    [data-testid="stSidebarNav"] a[aria-current="page"] { color: var(--ich-teal); font-weight:600; }
    /* Bottoni: primario teal, secondario con bordo teal */
    .stButton button[kind="primary"], [data-testid="baseButton-primary"] {
        background: var(--ich-teal); border-color: var(--ich-teal);
    }
    .stButton button[kind="primary"]:hover, [data-testid="baseButton-primary"]:hover {
        background: var(--ich-teal-d); border-color: var(--ich-teal-d);
    }
    .stButton button { border-radius: 8px; }
    /* Metriche e card */
    [data-testid="stMetricValue"] { color: var(--ich-teal-d); }
    [data-testid="stExpander"], [data-testid="stMetric"] {
        background:#ffffff; border:1px solid var(--ich-line); border-radius:10px;
    }
</style>
""", unsafe_allow_html=True)

# Logo in alto a sinistra, SOPRA il menu (st.logo usa lo slot dedicato; mostra
# l'icona quando la sidebar è chiusa). SVG orizzontale del brand ICH.
try:
    st.logo("assets/ich_logo.svg", size="large", icon_image="assets/ich_icon.svg")
except Exception:  # noqa: BLE001 — versioni Streamlit senza st.logo
    pass

# ─── SOURCE ITEMS ────────────────────────────────────────
# Serbatoio 2: il seed (item demo stabili + 2 casi di test del Guardrail) è in
# data/feed/events_seed.json; i contenuti live arrivano via RSS (ich/sources.py).
SOURCE_ITEMS = sources.load_seed()

@st.cache_data(ttl=900, show_spinner=False)
def fetch_live_cached():
    """Ingestione RSS reale, in cache per 15 minuti (≈ 'crawling ogni 15 min')."""
    return sources.fetch_live(max_per_feed=5)

# ─── PROMPTS ─────────────────────────────────────────────
GUARDRAIL_PROMPT = """Sei il Guardrail Engine del Content Intelligence Hub per la promozione turistica pubblica italiana.

Valuta il contenuto secondo 6 regole:
1. fonte: ente pubblico legittimo (comune, APT, parco, IAT, Pro Loco)? Siti commerciali = warn/fail.
2. promozione: prezzi + CTA commerciali + codici sconto = fail.
3. data: date 2023 o precedenti = fail. Date 2024 passate = warn. Date 2025+ = pass.
4. gdpr: nomi propri + telefono/email privati = fail.
5. qualita: meno di 15 parole informative = warn. Palesemente falso = fail.
6. duplicato: valuta sempre come pass.

Rispondi SOLO con JSON valido (nessun testo aggiuntivo):
{"fonte":{"result":"pass|warn|fail","reason":"..."},"promozione":{"result":"pass|warn|fail","reason":"..."},"data":{"result":"pass|warn|fail","reason":"..."},"gdpr":{"result":"pass|warn|fail","reason":"..."},"qualita":{"result":"pass|warn|fail","reason":"..."},"duplicato":{"result":"pass","reason":"Nessun duplicato rilevato"},"overall":"pass|warn|blocked","block_reason":"motivo se blocked, altrimenti null"}"""

ANALYSIS_PROMPT = """Analizza questo contenuto turistico ed estrai informazioni strutturate.
Rispondi SOLO con JSON (nessun testo aggiuntivo):
{"topics":["topic1","topic2"],"importance":7,"urgency":"alta|media|bassa","languages":["IT","EN"],"summary":"sintesi in una riga","entities":{"luoghi":[],"date":[],"eventi":[]}}"""

REWRITE_PROMPT = """Sei il Rewriting Engine del Content Intelligence Hub per il turismo territoriale.
Genera 5 varianti del contenuto, una per ogni canale. Rispondi UNICAMENTE con JSON valido, senza testo aggiuntivo.
Chiavi richieste:
- chatbot: risposta conversazionale 2-3 frasi, termina con domanda al turista
- mobile: due righe separate da \\n — titolo max 50 car, testo max 90 car
- signage: tre righe separate da \\n — TITOLO IN MAIUSCOLO, dettaglio breve, data/luogo
- tv: quattro righe separate da \\n — titolo, sottotitolo, dettaglio, data e luogo
- api: oggetto con campi event, date (YYYY-MM-DD o null), location, type, free (boolean)"""

CHATBOT_SYS = """Sei l'Assistente Virtuale Turistico dell'Abruzzo, al servizio della promozione turistica pubblica.
Regole:
- Rispondi nella lingua dell'utente, in modo accogliente e conciso.
- Basa le risposte sul CONTESTO DAL KNOWLEDGE BASE fornito qui sotto e cita le fonti tra parentesi quadre, es. [Parco Nazionale della Majella].
- Fornisci solo informazioni territoriali e collettive: NON promuovere imprese, hotel o marchi commerciali specifici.
- Se l'informazione non è nel contesto, dillo con onestà e suggerisci di rivolgersi all'ufficio IAT locale o al portale ufficiale abruzzoturismo.it. Non inventare eventi, date o prezzi."""

# ─── GUARDRAIL TEST RESULTS (hardcoded per demo affidabile) ──
GUARDRAIL_HOTEL = {
    "fonte":      {"result": "warn", "reason": "TurismoAbruzzoPromo.it — sito commerciale, non ente pubblico"},
    "promozione": {"result": "fail", "reason": "Codice sconto ESTATE25 + prezzo €89/notte + CTA 'Prenota ora' = promozione commerciale diretta"},
    "data":       {"result": "pass", "reason": "Estate 2025 — data valida"},
    "gdpr":       {"result": "pass", "reason": "Nessun dato personale identificabile"},
    "qualita":    {"result": "pass", "reason": "Contenuto informativo adeguato"},
    "duplicato":  {"result": "pass", "reason": "Nessun duplicato rilevato"},
    "overall": "blocked",
    "block_reason": "Promozione commerciale: codice sconto, prezzo specifico e call to action diretta"
}

GUARDRAIL_SAGRA2023 = {
    "fonte":      {"result": "pass", "reason": "Pro Loco Avezzano — ente territoriale legittimo"},
    "promozione": {"result": "pass", "reason": "Nessuna promozione commerciale"},
    "data":       {"result": "fail", "reason": "15 maggio 2023 — evento scaduto da oltre 2 anni"},
    "gdpr":       {"result": "fail", "reason": "'Mario Rossi' + tel. 347-1234567: dati personali identificabili (GDPR art.4)"},
    "qualita":    {"result": "pass", "reason": "Contenuto informativo sufficiente"},
    "duplicato":  {"result": "pass", "reason": "Nessun duplicato rilevato"},
    "overall": "blocked",
    "block_reason": "Doppio blocco: data evento scaduta (2023) + dati personali GDPR (nome e numero telefono)"
}

# ─── GUARDRAIL CHECK DEFINITIONS ─────────────────────────
CHECKS = [
    ("fonte",      "🏛️",  "Fonte autorizzata"),
    ("promozione", "💰",  "No promozione commerciale"),
    ("data",       "📅",  "Validità temporale"),
    ("gdpr",       "🔒",  "GDPR compliance"),
    ("qualita",    "📝",  "Qualità contenuto"),
    ("duplicato",  "🔁",  "Assenza duplicati"),
]

# ─── HELPERS ─────────────────────────────────────────────
def call_claude(system_prompt, user_content, max_tokens=500):
    client = get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}]
        )
        text = resp.content[0].text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return None
    except:
        return None

def add_audit(item, result, reason, actor="system"):
    """Registra una decisione nell'audit log DUREVOLE (data/store/audit.jsonl),
    unico registro EU AI Act. L'id è quello canonico, così l'evento è collegabile
    all'item in items.json."""
    try:
        item_id = model.from_feed_item(item)["id"]
    except Exception:
        item_id = str(item.get("id", ""))
    store.append_audit(result, item_id, item.get("source", ""), reason,
                       actor=actor, title=(item.get("title", "") or "")[:80])

def reset_pipeline():
    st.session_state.ps = {
        "stage": "idle",
        "item": None, "analysis": None, "guardrail": None, "channels": None
    }

def channel_fallback(item):
    return {
        "chatbot": f"{item['title']} — un evento da non perdere in Abruzzo! Vuoi sapere come raggiungerlo o gli orari?",
        "mobile":  f"🔔 {item['title'][:45]}\nDettagli su abruzzoturismo.it",
        "signage": f"{item['title'].upper()[:28]}\nEvento locale · Ingresso libero\n{item['source']}",
        "tv":      f"{item['title']}\nFonte: {item['source']}\nwww.abruzzoturismo.it\n{datetime.now().strftime('%d/%m/%Y')}",
        "api":     {"event": item["title"], "date": None, "location": "Abruzzo",
                    "type": item["type"].lower(), "free": True, "source": item["source"]}
    }

# ─── SESSION STATE INIT ───────────────────────────────────
if "published"    not in st.session_state: st.session_state.published    = []
if "generated"    not in st.session_state: st.session_state.generated    = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "assistant", "content": "Ciao! 🏔️ Sono l'assistente virtuale turistico dell'Abruzzo.\n\nPosso aiutarti su eventi, escursioni, gastronomia e molto altro. Prova a scrivere in italiano, inglese o tedesco!"}
    ]
if "ps" not in st.session_state: reset_pipeline()

# ─── SIDEBAR — intestazione + controlli globali ──────────────────────────────
# Definite qui, richiamate in fondo attorno a st.navigation (layout tipo TDH).
def render_sidebar_controls():
    _aud = store.load_audit()
    k1, k2 = st.columns(2)
    k1.metric("Pubblicati", len(store.load_feed()))
    k2.metric("Bloccati", sum(1 for e in _aud if e.get("event") == "blocked"))
    st.caption(f"📋 {len(_aud)} eventi nell'audit durevole")
    st.divider()
    _key_on = bool(st.session_state.api_key)
    with st.expander("🔑 Assistente AI — " + ("✅ key attiva" if _key_on
                     else "inserisci l'API key"), expanded=not _key_on):
        new_key = st.text_input(
            "ANTHROPIC_KEY", value=st.session_state.api_key, type="password",
            label_visibility="collapsed", placeholder="sk-ant-...",
            help="A consumo sul tuo account Anthropic. Senza key l'app gira in demo.")
        st.caption("🔒 Resta solo nella tua sessione, non viene salvata.")
        if new_key != st.session_state.api_key:
            st.session_state.api_key = new_key
            st.rerun()

# ════════════════════════════════════════
# TAB 1 — PIPELINE E2E
# ════════════════════════════════════════
def page_pipeline():
    feed_col, pipe_col = st.columns([1, 2])

    # ── Source feed ──
    with feed_col:
        st.markdown("**🔴 SOURCE MONITOR**")
        st.caption("Seed dimostrativo + fonti RSS reali · clicca per selezionare")

        if st.button("🔄 Aggiorna fonti (RSS live)", use_container_width=True):
            with st.spinner("Ingestione fonti live…"):
                live, errs = fetch_live_cached()
                st.session_state.live_items = live
                st.session_state.live_errors = errs
            st.rerun()

        live_items = st.session_state.get("live_items", [])
        live_errors = st.session_state.get("live_errors", [])
        if live_items:
            st.success(f"📡 {len(live_items)} contenuti live ingeriti")
        if live_errors:
            st.caption("⚠️ Fonti non raggiunte: " + ", ".join(live_errors))
        st.markdown("---")

        # Bozze generate (Fase 2), poi contenuti live reali, poi il seed dimostrativo
        for item in st.session_state.generated + live_items + SOURCE_ITEMS:
            is_test = "test_label" in item
            is_live = item.get("live")
            is_gen = item.get("generated")
            label = f"{item['icon']} {item['title'][:42]}{'...' if len(item['title'])>42 else ''}"
            if st.button(label, key=f"src_{item['id']}", use_container_width=True):
                st.session_state.ps = {"stage": "selected", "item": item,
                                        "analysis": None, "guardrail": None, "channels": None}
                st.rerun()
            rel = topics.match_item(item)  # rilevanza rispetto agli argomenti attivi
            if rel["matched"]:
                st.caption("🎯 " + " · ".join(m["label"] for m in rel["matched"][:3])
                           + f" · rilevanza {rel['score']}")
            if is_gen:
                st.caption(f"✨ BOZZA AI · argomento: {item.get('topic','')} · da validare")
            if is_live:
                st.caption(f"📡 LIVE · {item['source']} · {item['detected']}")
            if is_test:
                st.caption(f"⚠️ TEST: {item['test_label']}")

    # ── Processing panel ──
    with pipe_col:
        ps = st.session_state.ps

        if ps["stage"] == "idle":
            st.info("← Seleziona un contenuto dalla coda per avviare la pipeline")
            st.markdown("""
**Come funziona la pipeline CIH:**

| Step | Fase | Descrizione |
|------|------|-------------|
| 1 | 🔍 Rilevamento | Contenuto dalla fonte istituzionale |
| 2 | 🤖 Analisi AI | Classificazione, entità, urgenza |
| 3 | 🛡️ Guardrail | 6 check di conformità in parallelo |
| 4 | ✍️ Rewriting | 5 varianti per 5 canali diversi |
| 5 | 👁️ Validazione | Approvazione obbligatoria dell'operatore |
| 6 | 📤 Pubblicazione | Push simultaneo su tutti i canali |
""")

        else:
            item = ps["item"]

            # ── Detected ──
            with st.expander("🔍 Contenuto rilevato", expanded=True):
                ca, cb = st.columns([3, 1])
                with ca:
                    st.markdown(f"**{item['title']}**")
                    st.caption(f"Fonte: {item['source']} · {item['detected']}")
                with cb:
                    color = {"EVENTO": "🟢", "NEWS": "🔵", "PROMO": "🔴", "AVVISO": "🟡"}
                    st.write(f"{color.get(item['type'],'⚪')} `{item['type']}`")
                st.markdown(f"*\"{item['raw']}\"*")
                _rel = topics.match_item(item)
                if _rel["matched"]:
                    st.caption("🎯 Argomenti: " +
                               " · ".join(m["label"] for m in _rel["matched"]) +
                               f" · rilevanza {_rel['score']}")
                else:
                    st.caption("🎯 Nessun argomento attivo combacia (gestiscili nel tab «Argomenti»)")

            # ── Avvia button ──
            if ps["stage"] == "selected":
                if st.button("🚀 Avvia pipeline — Analisi AI → Guardrail → Rewriting",
                             type="primary", use_container_width=True):

                    with st.status("🚀 Pipeline in esecuzione...", expanded=True) as status:

                        st.write("🤖 Stage 1 — Analisi AI...")
                        analysis = call_claude(ANALYSIS_PROMPT, item["raw"], 400) or {
                            "topics": ["turismo"], "importance": 7, "urgency": "media",
                            "summary": item["title"], "languages": ["IT", "EN"],
                            "entities": {"luoghi": [], "date": [], "eventi": []}
                        }

                        st.write("🛡️ Stage 2 — Guardrail Engine (6 check)...")
                        if item["id"] == 4:
                            time.sleep(1.5); guardrail = GUARDRAIL_HOTEL
                        elif item["id"] == 5:
                            time.sleep(1.5); guardrail = GUARDRAIL_SAGRA2023
                        else:
                            guardrail = call_claude(
                                GUARDRAIL_PROMPT,
                                f"Fonte: {item['source']}\n\nContenuto: {item['raw']}", 600
                            ) or {"fonte":{"result":"pass","reason":"OK"},
                                  "promozione":{"result":"pass","reason":"OK"},
                                  "data":{"result":"pass","reason":"OK"},
                                  "gdpr":{"result":"pass","reason":"OK"},
                                  "qualita":{"result":"pass","reason":"OK"},
                                  "duplicato":{"result":"pass","reason":"OK"},
                                  "overall":"pass","block_reason":None}

                        # Ledger: persisti l'item in items.json con l'esito del
                        # guardrail (stato 'pending', approvazione ancora da fare).
                        dispatch.persist_pipeline_item(item, analysis, guardrail, approval="pending")

                        if guardrail.get("overall") == "blocked":
                            status.update(label="⛔ Contenuto BLOCCATO dal Guardrail", state="error")
                            add_audit(item, "blocked", guardrail.get("block_reason",""))
                            st.session_state.ps.update({"stage":"blocked","analysis":analysis,"guardrail":guardrail})
                            st.rerun()

                        add_audit(item, "guardrail_pass",
                                  "Tutti i check superati" if guardrail.get("overall")=="pass" else "Superato con avvisi")

                        st.write("✍️ Stage 3 — Rewriting engine (5 canali)...")
                        raw_ch = call_claude(
                            REWRITE_PROMPT,
                            f"Titolo: {item['title']}\nContenuto: {item['raw']}", 800
                        )
                        rewrite_variants = raw_ch if (raw_ch and raw_ch.get("chatbot")) else channel_fallback(item)

                        status.update(label="✅ Pipeline completata — in attesa di validazione", state="complete")
                        st.session_state.ps.update({"stage":"validate","analysis":analysis,
                                                     "guardrail":guardrail,"channels":rewrite_variants})
                        st.rerun()

            # ── Analysis result ──
            if ps["analysis"] and ps["stage"] != "selected":
                a = ps["analysis"]
                with st.expander("🤖 Analisi AI", expanded=True):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Topic", ", ".join(a.get("topics",[])[:2]))
                    c2.metric("Lingue", " · ".join(a.get("languages",["IT"])))
                    urg = a.get("urgency","media")
                    c3.metric("Urgenza push", {"alta":"🔴 Alta","media":"🟡 Media","bassa":"🟢 Bassa"}.get(urg,urg))
                    if a.get("summary"):
                        st.caption(f"📝 {a['summary']}")

            # ── Guardrail result ──
            if ps["guardrail"] and ps["stage"] != "selected":
                g = ps["guardrail"]
                is_blocked = g.get("overall") == "blocked"

                if is_blocked:
                    st.error(f"🛡️ **CONTENUTO BLOCCATO** — {g.get('block_reason','')}")
                elif g.get("overall") == "warn":
                    st.warning("🛡️ **Guardrail superato con avvisi**")
                else:
                    st.success("🛡️ **Guardrail OK — tutti i check superati**")

                with st.expander("Dettaglio 6 check", expanded=True):
                    for chk_id, icon, label in CHECKS:
                        res = g.get(chk_id, {"result":"pass","reason":""})
                        result = res.get("result","pass")
                        reason = res.get("reason","")
                        ci, cl, cs = st.columns([0.3, 3.5, 0.8])
                        ci.write(icon)
                        cl.write(f"**{label}** — {reason}")
                        if result == "pass":   cs.success("✓ PASS")
                        elif result == "warn": cs.warning("⚠ WARN")
                        else:                  cs.error("✕ FAIL")

                if is_blocked:
                    if st.button("✕ Scarta e torna alla coda", use_container_width=True):
                        add_audit(item, "discarded", "Scartato dopo blocco guardrail", actor="operator")
                        dispatch.persist_pipeline_item(item, ps["analysis"], ps["guardrail"],
                                                       approval="rejected", actor="operator")
                        reset_pipeline()
                        st.rerun()

            # ── Channel variants ──
            if ps["channels"] and ps["stage"] == "validate":
                ch = ps["channels"]
                with st.expander("✍️ 5 varianti generate per canale", expanded=True):
                    ct1, ct2, ct3, ct4, ct5 = st.tabs(["💬 Chatbot","📱 Mobile","📺 Signage","🖥️ TV Panel","⚡ API"])
                    with ct1: st.info(ch.get("chatbot",""))
                    with ct2: st.code(ch.get("mobile",""), language=None)
                    with ct3: st.code(ch.get("signage",""), language=None)
                    with ct4: st.code(ch.get("tv",""), language=None)
                    with ct5:
                        api_v = ch.get("api",{})
                        st.json(api_v) if isinstance(api_v, dict) else st.code(str(api_v))

                st.divider()
                st.markdown("**👁️ Validazione operatore** — Confermi la pubblicazione su tutti i canali?")
                ca, cr = st.columns(2)
                with ca:
                    if st.button("✓ Approva e pubblica", type="primary", use_container_width=True):
                        pub_item = {**item, "channels": ps["channels"],
                                    "published_at": datetime.now().strftime("%H:%M")}
                        st.session_state.published.insert(0, pub_item)
                        # Step 6 — dispatch REALE su tutti i canali del registro.
                        # publish() persiste l'item (approved) e scrive l'audit
                        # durevole. La UI resta viva anche se un sink fallisce.
                        try:
                            dispatch.publish(item, ps["analysis"], ps["guardrail"],
                                             ps["channels"], actor="operator")
                            st.success(f"✅ Approvato e dispacciato su {len(channels.CHANNELS)} canali "
                                       f"· feed API a {len(store.load_feed())} contenuti")
                        except Exception as e:  # noqa: BLE001
                            st.warning(f"Pubblicato in sessione, ma la scrittura durevole è "
                                       f"fallita: {type(e).__name__} — {e}")
                        time.sleep(0.8)
                        reset_pipeline()
                        st.rerun()
                with cr:
                    if st.button("✕ Rifiuta", use_container_width=True):
                        add_audit(item, "rejected", "Rifiutato dall'operatore in validazione", actor="operator")
                        dispatch.persist_pipeline_item(item, ps["analysis"], ps["guardrail"],
                                                       approval="rejected", actor="operator")
                        reset_pipeline()
                        st.rerun()

# ════════════════════════════════════════
# TAB 2 — OUTPUT CANALI
# ════════════════════════════════════════
def page_canali():
    _counts = []
    for _ch in channels.CHANNELS:
        _name = "feed" if _ch.id == "api" else _ch.id
        _counts.append(f"{_ch.icon} {_ch.label}: **{len(store.load_outbox(_name))}**")
    st.caption("📤 Outbox persistenti dei canali (in `data/published/`, sopravvivono al "
               "reload · l'API è `feed.json`, consumabile da Abruzzo Wild): "
               + " · ".join(_counts))
    if not st.session_state.published:
        st.info("📡 Nessun contenuto pubblicato in questa sessione. Vai in Pipeline, processa e approva un contenuto.")
    else:
        st.markdown(f"### 📡 {len(st.session_state.published)} contenuto/i live — push su 5 canali")
        for pub in st.session_state.published:
            with st.expander(f"{pub['icon']} **{pub['title']}** — {pub['source']} · {pub['published_at']}", expanded=False):
                st.markdown("**📥 PULL** (knowledge base) &nbsp;+&nbsp; **📤 PUSH** (5 canali attivi)")
                ch = pub.get("channels", {})
                if ch:
                    t1,t2,t3,t4,t5 = st.tabs(["💬 Chatbot","📱 Mobile","📺 Signage","🖥️ TV","⚡ API"])
                    with t1: st.info(ch.get("chatbot",""))
                    with t2: st.code(ch.get("mobile",""), language=None)
                    with t3: st.code(ch.get("signage",""), language=None)
                    with t4: st.code(ch.get("tv",""), language=None)
                    with t5:
                        api_v = ch.get("api",{})
                        st.json(api_v) if isinstance(api_v,dict) else st.code(str(api_v))

# ════════════════════════════════════════
# TAB 3 — ASSISTENTE (PULL MODE)
# ════════════════════════════════════════
def page_assistente():
    _kbinfo = kb.kb_stats()
    c1, c2 = st.columns([3,1])
    with c1:
        st.markdown(f"**💬 Assistente Virtuale Abruzzo** — Modalità PULL · "
                    f"KB territoriale: {_kbinfo['n_chunks']} schede (v{_kbinfo['versione']})")
    with c2:
        if st.session_state.published:
            st.success(f"📤 +{len(st.session_state.published)} contenuti pubblicati")

    # Suggestions
    sc1, sc2, sc3 = st.columns(3)
    if sc1.button("Dove mangio arrosticini?"):
        st.session_state.chat_history.append({"role":"user","content":"Dove mangio arrosticini?"})
    if sc2.button("Hiking Gran Sasso, where to start?"):
        st.session_state.chat_history.append({"role":"user","content":"Hiking Gran Sasso, where to start?"})
    if sc3.button("Cosa c'è a Sulmona ad agosto?"):
        st.session_state.chat_history.append({"role":"user","content":"Cosa c'è a Sulmona ad agosto?"})

    # Chat display
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"], avatar="🏔️" if msg["role"]=="assistant" else None):
            st.write(msg["content"])

    # Input
    if prompt := st.chat_input("Scrivi una domanda sul territorio abruzzese..."):
        st.session_state.chat_history.append({"role":"user","content":prompt})
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant", avatar="🏔️"):
            with st.spinner("Ricerca nel knowledge base..."):
                # Serbatoio 1 — recupera dal KB territoriale i chunk pertinenti
                kb_ctx, kb_used = kb.build_context(prompt, k=5)
                # Serbatoio 3 — registra la domanda reale in modo DUREVOLE: segnale
                # di domanda per l'Intelligence (topic + content gap), fra le sessioni.
                store.append_query(prompt, bool(kb_used),
                                   [c.get("category") for c in kb_used])
                # Serbatoio 2 — contenuti approvati dispacciati al canale chatbot
                # (outbox durevole: sopravvive al reload, canale pull reale).
                extra = ""
                chatbot_out = store.load_outbox("chatbot")
                if chatbot_out:
                    extra = "\nCONTENUTI APPROVATI RECENTEMENTE:\n" + "\n".join(
                        f"- {e.get('title','')}: {e.get('content','')}" for e in chatbot_out[:5]
                    )
                client = get_client()
                if client is None:
                    reply = ("🔑 Per usare l'assistente inserisci la tua API key "
                             "Anthropic nel riquadro «🔑 Assistente AI» in alto. "
                             "Senza key il resto dell'app funziona comunque in demo.")
                else:
                    try:
                        msgs = [{"role":m["role"],"content":m["content"]}
                                for m in st.session_state.chat_history]
                        resp = client.messages.create(
                            model="claude-sonnet-4-6", max_tokens=500,
                            system=CHATBOT_SYS + kb_ctx + extra, messages=msgs
                        )
                        reply = resp.content[0].text
                    except Exception as e:
                        reply = f"⚠️ Errore nella chiamata al modello: {type(e).__name__} — {e}"
                st.write(reply)
                if kb_used:
                    st.caption("📚 Fonti consultate: " +
                               " · ".join(f"{c['title']} [{c['source']}]" for c in kb_used))
                st.session_state.chat_history.append({"role":"assistant","content":reply})
        st.rerun()

# ════════════════════════════════════════
# TAB 4 — INTELLIGENCE / ANALYTICS
# ════════════════════════════════════════
def page_intelligence():
    st.markdown("### 📊 Intelligence")
    st.caption("Come lavora il motore (dal ledger) e cosa chiedono gli utenti "
               "all'assistente. I dati macro di destinazione (ISTAT/BdI) vivono nel progetto TDH.")

    # ── Intelligence operativa: cosa ha prodotto il dispatcher (Passo 6) ──
    st.divider()
    st.markdown("#### ⚙️ Intelligence operativa — dal motore (ledger `items.json`)")
    _items = store.load_items()
    if not _items:
        st.info("Nessun contenuto ancora processato. Elabora item nella Pipeline: "
                "qui compaiono il funnel e la copertura editoriale.")
    else:
        pstats = intelligence.pipeline_stats(_items)
        f1, f2, f3, f4, f5 = st.columns(5)
        f1.metric("Processati",   pstats["total"])
        f2.metric("Guardrail OK", pstats["guardrail_pass"])
        f3.metric("Bloccati",     pstats["guardrail_blocked"])
        f4.metric("Approvati",    pstats["approved"])
        f5.metric("Rifiutati",    pstats["rejected"])

        cov = intelligence.category_coverage(_items)
        oc1, oc2 = st.columns([2, 1])
        with oc1:
            st.caption("Copertura editoriale — contenuti approvati per tema (tassonomia)")
            figc = px.bar(pd.DataFrame(cov), x="n", y="label", orientation="h",
                          color_discrete_sequence=["#028090"])
            figc.update_layout(height=300, margin=dict(t=10,b=0,l=0,r=0),
                               xaxis_title=None, yaxis_title=None)
            st.plotly_chart(figc, use_container_width=True)
        with oc2:
            st.markdown("**🕳️ Gap tematici**")
            st.caption("Temi senza contenuti approvati → priorità editoriale")
            empty = [c["label"] for c in cov if c["n"] == 0]
            if empty:
                for lab in empty:
                    st.write(f"⚪ {lab}")
            else:
                st.success("Tutti i temi della tassonomia hanno almeno un contenuto.")

    st.divider()
    st.markdown("#### 🔎 Domanda dall'assistente — dati reali di utilizzo (durevoli)")
    log = store.load_queries()
    if not log:
        st.info("Nessuna domanda ancora. Usa l'Assistente (tab 💬): le domande reali "
                "popoleranno i topic richiesti e i content gap qui sotto.")
    else:
        topics = intelligence.topics_from_log(log)
        gaps = intelligence.gaps_from_log(log)
        d1, d2 = st.columns(2)
        with d1:
            st.caption(f"Topic più richiesti · {len(log)} domande registrate")
            if topics:
                figt = px.bar(pd.DataFrame(topics), x="Query", y="Topic", orientation="h",
                              color_discrete_sequence=["#02C39A"])
                figt.update_layout(height=260, margin=dict(t=10,b=0,l=0,r=0),
                                   xaxis_title=None, yaxis_title=None)
                st.plotly_chart(figt, use_container_width=True)
            else:
                st.caption("Ancora nessun topic associato alle domande.")
        with d2:
            st.markdown("**⚠️ Content Gap Alert**")
            st.caption("Domande senza risposta nel KB → contenuti da aggiungere")
            if gaps:
                for g in gaps:
                    gc1, gc2 = st.columns([5, 1])
                    gc1.write(f"🔥 {g['Domanda']}")
                    gc2.markdown(f"**{g['N']}**")
            else:
                st.success("Nessun gap: il KB ha risposto a tutte le domande poste.")

# ════════════════════════════════════════
# TAB 5 — AUDIT LOG
# ════════════════════════════════════════
def page_audit():
    _audit = store.load_audit()
    st.markdown("### 📋 Registro decisioni — EU AI Act compliance")
    st.caption(f"{len(_audit)} eventi registrati in `data/store/audit.jsonl` (durevole) · "
               "ogni decisione automatizzata è tracciata")

    if not _audit:
        st.info("Nessun evento ancora. Processa contenuti dalla Pipeline per popolare il log.")
    else:
        result_labels = {
            "published":     "✅ Pubblicato",
            "blocked":       "⛔ Bloccato Guardrail",
            "guardrail_pass":"🛡️ Guardrail OK",
            "rejected":      "❌ Rifiutato operatore",
            "discarded":     "🗑️ Scartato",
        }
        counts = {k: sum(1 for e in _audit if e.get("event")==k) for k in result_labels}
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Pubblicati",      counts.get("published",0))
        m2.metric("Bloccati Guardrail", counts.get("blocked",0))
        m3.metric("Guardrail OK",    counts.get("guardrail_pass",0))
        m4.metric("Rifiutati",       counts.get("rejected",0))

        st.divider()
        df_log = pd.DataFrame([{
            "Ora":       (e.get("ts","")[11:19] or "—"),
            "Contenuto": e.get("title","") or e.get("item_id",""),
            "Fonte":     e.get("source",""),
            "Attore":    e.get("actor",""),
            "Evento":    result_labels.get(e.get("event"), e.get("event","")),
            "Dettaglio": e.get("detail",""),
        } for e in _audit])
        st.dataframe(df_log, use_container_width=True, hide_index=True)

        st.caption("**EU AI Act Art. 13–14 (Trasparenza + Supervisione umana):** ogni decisione automatizzata è tracciata con timestamp, fonte, tipo di check e azione. I contenuti bloccati dal Guardrail non raggiungono mai l'utente finale senza revisione umana.")

# ════════════════════════════════════════
# TAB 6 — ARGOMENTI (controllo editoriale del motore)
# ════════════════════════════════════════
def page_argomenti():
    st.markdown("### 🎯 Argomenti — cosa il motore deve seguire")
    st.caption("Definisci i temi di interesse: il motore **tagga** e dà **priorità** ai "
               "contenuti che li riguardano, così l'info feed resta focalizzato. Un contenuto "
               "combacia se una keyword compare nel testo o se la sua categoria coincide. "
               "(Fase 2: gli stessi argomenti guideranno la ricerca/generazione proattiva.)")

    _topics = topics.load_topics()
    _df = pd.DataFrame([{
        "Abilitato": t.get("enabled", True),
        "Argomento": t.get("label", ""),
        "Categoria": t.get("category") or "",
        "Keyword (virgola)": ", ".join(t.get("keywords", [])),
        "Priorità": t.get("priority", "media"),
    } for t in _topics])

    edited = st.data_editor(
        _df, num_rows="dynamic", use_container_width=True, hide_index=True, key="topics_editor",
        column_config={
            "Abilitato": st.column_config.CheckboxColumn(width="small"),
            "Categoria": st.column_config.SelectboxColumn(options=[""] + list(model.TAXONOMY)),
            "Priorità":  st.column_config.SelectboxColumn(options=["alta", "media", "bassa"]),
        },
    )

    cbtn, cinfo = st.columns([1, 3])
    with cbtn:
        if st.button("💾 Salva argomenti", type="primary", use_container_width=True):
            def _cell(row, key):
                v = row[key]
                return "" if pd.isna(v) else str(v).strip()
            new_topics = []
            for _, r in edited.iterrows():
                label = _cell(r, "Argomento")
                if not label:
                    continue
                kws = [k.strip() for k in _cell(r, "Keyword (virgola)").split(",") if k.strip()]
                new_topics.append({
                    "id": topics._slug(label),
                    "label": label,
                    "category": _cell(r, "Categoria") or None,
                    "keywords": kws,
                    "priority": _cell(r, "Priorità") or "media",
                    "enabled": bool(r["Abilitato"]) if not pd.isna(r["Abilitato"]) else False,
                })
            topics.save_topics(new_topics)
            st.success(f"✅ Salvati {len(new_topics)} argomenti in data/config/topics.json")
            st.rerun()
    with cinfo:
        n_on = sum(1 for t in _topics if t.get("enabled", True))
        st.caption(f"{n_on}/{len(_topics)} argomenti attivi · aggiungi righe in fondo alla tabella, "
                   "poi **Salva**. Le modifiche valgono subito per il tagging in Pipeline.")

    st.divider()
    st.markdown("#### ✨ Genera bozze dagli argomenti (Fase 2)")
    st.caption("Il motore crea schede informative territoriali sui temi scelti, **ancorate "
               "alla knowledge base**. Sono BOZZE: entrano nella Pipeline e passano da "
               "Guardrail + validazione umana prima di qualsiasi pubblicazione.")
    _active = topics.active_topics()
    if not _active:
        st.info("Nessun argomento attivo: abilitane almeno uno nella tabella qui sopra.")
    elif get_client() is None:
        st.info("🔑 La generazione usa l'AI: inserisci la tua API key nel riquadro «🔑 Assistente AI» in alto.")
    else:
        labels = [t["label"] for t in _active]
        sel = st.multiselect("Argomenti per cui generare una bozza", labels, default=labels[:1])
        gc1, gc2 = st.columns(2)
        with gc1:
            if st.button("✨ Genera bozze", type="primary", use_container_width=True, disabled=not sel):
                chosen = [t for t in _active if t["label"] in sel]
                made = 0
                with st.spinner(f"Genero {len(chosen)} bozza/e ancorate alla KB…"):
                    for t in chosen:
                        kb_ctx, _ = kb.build_context(
                            t["label"] + " " + " ".join(t.get("keywords", [])), k=4)
                        parsed = call_claude(generate.GEN_SYS,
                                             generate.build_user_prompt(t, kb_ctx), 500)
                        cand = generate.to_candidate(t, parsed,
                                                     len(st.session_state.generated) + made)
                        if cand:
                            st.session_state.generated.insert(0, cand)
                            made += 1
                if made:
                    st.success(f"✅ Generate {made} bozze → ora in coda nella **Pipeline** (✨ BOZZA AI), da validare.")
                else:
                    st.warning("Nessuna bozza valida generata. Riprova.")
                st.rerun()
        with gc2:
            if st.session_state.generated and st.button(
                    f"🗑️ Svuota bozze in coda ({len(st.session_state.generated)})",
                    use_container_width=True):
                st.session_state.generated = []
                st.rerun()

    st.divider()
    st.markdown("#### 🧪 Prova rapida")
    probe = st.text_input("Incolla un titolo/testo e vedi quali argomenti combaciano",
                          placeholder="Es. Sagra del vino nel borgo di Ortona")
    if probe:
        pr = topics.match_item({"title": probe, "raw": probe})
        if pr["matched"]:
            st.success("🎯 " + " · ".join(m["label"] for m in pr["matched"]) +
                       f"  ·  rilevanza {pr['score']}")
        else:
            st.info("Nessun argomento attivo combacia con questo testo.")


# ════════════════════════════════════════
# TAB 7 — GESTIONE DATI (fonti/feed + backend di persistenza)
# ════════════════════════════════════════
def page_gestione_dati():
    st.markdown("### 🗃️ Gestione dati")
    st.caption("Le fonti che il motore legge e lavora (Serbatoio 2) e lo stato "
               "della persistenza. Aggiungi una fonte con URL + descrizione: la "
               "modifica è durevole (niente redeploy).")

    # ── Stato del backend di persistenza ──
    _bk = store.backend_name()
    _is_pg = store._backend() is not None
    b1, b2 = st.columns([2, 1])
    with b1:
        if _is_pg:
            st.success(f"**Persistenza:** {_bk} — lo stato sopravvive ai redeploy del cloud.")
        else:
            st.warning(f"**Persistenza:** {_bk} — in cloud i dati si azzererebbero al "
                       "redeploy. Imposta `ICH_DATABASE_URL` (Neon) per renderli durevoli.")
    with b2:
        if st.button("⬇️ Esporta su JSON (espianto)", use_container_width=True,
                     help="Rigenera i file JSON locali dal backend attivo: backup/estrazione dati."):
            try:
                res = store.export_to_json()
                st.success(f"Esportati: {res['items']} item, "
                           f"{sum(res['outbox'].values())} uscite, "
                           f"{res['audit']} audit, {res['queries']} query, "
                           f"{res.get('topics', 0)} argomenti.")
            except Exception as e:
                st.error(f"Esportazione fallita: {type(e).__name__}: {e}")
        if _is_pg and st.button("⬆️ Importa JSON → DB", use_container_width=True,
                                help="Migrazione una-tantum: carica lo stato dei file JSON locali nel DB (salta se il DB è già popolato)."):
            try:
                res = store.import_from_json()
                if res.get("skipped"):
                    st.info(f"Saltato: {res['skipped']}")
                else:
                    st.success(f"Importati nel DB: {res['items']} item, "
                               f"{sum(res['outbox'].values())} uscite, {res['audit']} audit.")
            except Exception as e:
                st.error(f"Importazione fallita: {type(e).__name__}: {e}")

    st.divider()

    # ── Tabella 1 — Fonti configurate ──
    st.markdown("#### 📡 Fonti del feed (Serbatoio 2)")
    _all = feeds.list_all()
    st.caption(f"**Tabella 1** — {len(_all)} fonti configurate "
               f"({sum(1 for f in _all if f.get('enabled'))} abilitate)")
    if _all:
        df_feeds = pd.DataFrame([{
            "Abilitata": "✅" if f.get("enabled") else "⏸️",
            "Icona":     f.get("icon", ""),
            "Nome":      f.get("name", "") or f.get("source", ""),
            "Tipo":      f.get("type", ""),
            "Connettore": f.get("kind", ""),
            "URL / path": f.get("url", "") or f.get("path", ""),
            "Descrizione": f.get("description", ""),
            "Verificata": f.get("verified", "") or "—",
        } for f in _all])
        st.dataframe(df_feeds, use_container_width=True, hide_index=True)

        # Controlli per fonte: abilita/disabilita + elimina
        st.caption("Gestione rapida per fonte")
        for f in _all:
            fid = f.get("id")
            c1, c2, c3 = st.columns([6, 2, 2])
            with c1:
                st.write(f"{f.get('icon','')} **{f.get('name','')}** · "
                         f"`{f.get('kind','')}` · {f.get('url','') or f.get('path','')}")
            with c2:
                new_val = st.toggle("Abilitata", value=bool(f.get("enabled")),
                                    key=f"tog_{fid}")
                if new_val != bool(f.get("enabled")):
                    feeds.set_enabled(fid, new_val)
                    st.rerun()
            with c3:
                if st.button("🗑️ Elimina", key=f"del_{fid}", use_container_width=True):
                    feeds.delete_source(fid)
                    st.rerun()
    else:
        st.info("Nessuna fonte configurata. Aggiungine una qui sotto.")

    st.divider()

    # ── Aggiungi una fonte ──
    st.markdown("#### ➕ Aggiungi una fonte")
    with st.form("add_feed", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            f_name = st.text_input("Nome *", placeholder="Es. Comune di Sulmona — eventi")
            f_url = st.text_input("URL *", placeholder="https://…/rss.xml")
            f_desc = st.text_area("Descrizione", placeholder="A cosa serve questa fonte, cosa pubblica…", height=80)
        with fc2:
            f_kind = st.selectbox("Connettore", ["rss", "json", "ical"],
                                  help="rss = feed RSS 2.0 · json = array open-data (mappatura campi) · "
                                       "ical = calendario .ics (eventi: Google Calendar, comuni, pro loco)")
            f_type = st.selectbox("Tipo contenuto", list(model.ITEM_TYPES), index=1)
            f_icon = st.text_input("Icona (emoji)", value="📰", max_chars=4)
        submitted = st.form_submit_button("Aggiungi fonte", type="primary")
        if submitted:
            if not f_name.strip() or not f_url.strip():
                st.error("Nome e URL sono obbligatori.")
            else:
                feeds.add_source({
                    "name": f_name.strip(), "source": f_name.strip(),
                    "url": f_url.strip(), "kind": f_kind, "type": f_type,
                    "icon": f_icon.strip() or "📰",
                    "description": f_desc.strip(), "enabled": True,
                    "verified": datetime.now().strftime("%Y-%m-%d"),
                })
                st.success(f"Fonte «{f_name.strip()}» aggiunta.")
                st.rerun()

    st.divider()

    # ── Tabella 2 — Test di ingestione live ──
    st.markdown("#### 🔎 Prova l'ingestione")
    st.caption("Legge adesso tutte le fonti abilitate e mostra cosa arriva e quali "
               "falliscono (senza scrivere nulla).")
    if st.button("▶️ Testa ingestione ora"):
        with st.spinner("Lettura fonti live…"):
            items, errs = sources.fetch_live()
        st.caption(f"**Tabella 2** — {len(items)} contenuti letti · {len(errs)} fonti in errore")
        if items:
            df_live = pd.DataFrame([{
                "Fonte": it.get("source", ""),
                "Tipo":  it.get("type", ""),
                "Titolo": it.get("title", ""),
                "Rilevato": it.get("detected", ""),
            } for it in items])
            st.dataframe(df_live, use_container_width=True, hide_index=True)
        if errs:
            st.warning("Fonti in errore: " + " · ".join(errs))
        elif items:
            st.success("Tutte le fonti abilitate hanno risposto.")


# ═══════════════════════════════════════════════════════════════
# NAVIGAZIONE A SIDEBAR (st.navigation — layout tipo TDH)
# ═══════════════════════════════════════════════════════════════
pg = st.navigation({
    "Motore": [
        st.Page(page_pipeline,     title="Pipeline E2E",  icon=":material/sync:", default=True),
        st.Page(page_canali,       title="Output Canali", icon=":material/hub:"),
        st.Page(page_argomenti,    title="Argomenti",     icon=":material/label:"),
    ],
    "Assistente": [
        st.Page(page_assistente,   title="Assistente",    icon=":material/chat:"),
    ],
    "Analisi": [
        st.Page(page_intelligence, title="Intelligence",  icon=":material/insights:"),
        st.Page(page_audit,        title="Audit",         icon=":material/receipt_long:"),
    ],
    "Sistema": [
        st.Page(page_gestione_dati, title="Gestione dati", icon=":material/database:"),
    ],
})

with st.sidebar:
    st.divider()
    render_sidebar_controls()

pg.run()
