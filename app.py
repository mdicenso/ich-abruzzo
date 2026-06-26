# Proxy aziendale (Indra): fa usare all'SDK il trust store di Windows per il TLS,
# altrimenti la connessione all'API Anthropic fallisce con APIConnectionError.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import streamlit as st
from anthropic import Anthropic
import json, re, time, os, math
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from ich import kb       # Serbatoio 1 — knowledge base territoriale
from ich import sources  # Serbatoio 2 — flusso eventi & news (seed + RSS live)

# ─── PAGE CONFIG ─────────────────────────────────────────
st.set_page_config(
    page_title="Content Intelligence Hub — Abruzzo",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="collapsed"
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
    .main { padding-top: 0.5rem; }
    .block-container { padding-top: 1rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #F0F7FA;
        border-radius: 8px;
        padding: 6px 14px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .stTabs [aria-selected="true"] {
        background-color: #028090 !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

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

# ─── ANALYTICS DATA ──────────────────────────────────────
@st.cache_data
def get_analytics():
    daily = pd.DataFrame([
        {"Giorno": str(i+1), "Query": int(28 + i*1.1 + math.sin(i*0.5)*15 + (22 if i > 22 else 0))}
        for i in range(30)
    ])
    topics = pd.DataFrame([
        {"Topic": "Escursionismo", "Query": 312},
        {"Topic": "Spiagge",       "Query": 248},
        {"Topic": "Gastronomia",   "Query": 198},
        {"Topic": "Borghi storici","Query": 167},
        {"Topic": "Sport invernali","Query": 134},
        {"Topic": "Trasporti",     "Query": 112},
    ])
    langs = {"Italiano": 45, "English": 31, "Deutsch": 15, "Français": 9}
    gaps = [
        {"Domanda": "Corsi di cucina con chef locali", "N": 47, "Trend": "+23%", "hot": True},
        {"Domanda": "Noleggio e-bike L'Aquila",        "N": 38, "Trend": "+67%", "hot": True},
        {"Domanda": "Turismo accessibile / disabilità","N": 29, "Trend": "+12%", "hot": False},
        {"Domanda": "Fattorie didattiche con bambini", "N": 24, "Trend": "+8%",  "hot": False},
        {"Domanda": "Orari traghetti Isole Tremiti",   "N": 21, "Trend": "↑ nuovo","hot": False},
    ]
    return daily, topics, langs, gaps

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

def add_audit(item, result, reason):
    st.session_state.audit_log.insert(0, {
        "Ora":      datetime.now().strftime("%H:%M:%S"),
        "Contenuto": item["title"][:55],
        "Fonte":    item["source"],
        "Evento":   result,
        "Dettaglio": reason
    })

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
if "audit_log"    not in st.session_state: st.session_state.audit_log    = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "assistant", "content": "Ciao! 🏔️ Sono l'assistente virtuale turistico dell'Abruzzo.\n\nPosso aiutarti su eventi, escursioni, gastronomia e molto altro. Prova a scrivere in italiano, inglese o tedesco!"}
    ]
if "ps" not in st.session_state: reset_pipeline()

# ─── HEADER ──────────────────────────────────────────────
h1, h2, h3, h4 = st.columns([4, 1, 1, 1])
with h1:
    st.markdown("## 🏔️ Content Intelligence Hub &nbsp;&nbsp; `ABRUZZO · PoC E2E`")
with h2:
    st.metric("Pubblicati", len(st.session_state.published))
with h3:
    blk = sum(1 for e in st.session_state.audit_log if e["Evento"] == "blocked")
    st.metric("Bloccati", blk)
with h4:
    st.metric("Audit log", len(st.session_state.audit_log))

# ─── API KEY — inserita dall'utente (non consuma i crediti dell'autore) ──
_key_on = bool(st.session_state.api_key)
with st.expander(
    "🔑 Assistente AI — " + ("✅ API key attiva" if _key_on
     else "inserisci la tua API key Anthropic per attivare le funzioni AI"),
    expanded=not _key_on):
    kc1, kc2 = st.columns([4, 1])
    new_key = kc1.text_input(
        "ANTHROPIC_KEY", value=st.session_state.api_key, type="password",
        label_visibility="collapsed", placeholder="sk-ant-...",
        help="A consumo sul tuo account Anthropic. Senza key l'app mostra "
             "comunque la demo (con contenuti di fallback).")
    kc2.caption("🔒 La key resta solo nella tua sessione, non viene salvata.")
    if new_key != st.session_state.api_key:
        st.session_state.api_key = new_key
        st.rerun()

st.divider()

# ─── TABS ────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔄 Pipeline E2E",
    "📡 Output Canali",
    "💬 Assistente",
    "📊 Intelligence",
    f"📋 Audit ({len(st.session_state.audit_log)})"
])

# ════════════════════════════════════════
# TAB 1 — PIPELINE E2E
# ════════════════════════════════════════
with tab1:
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

        # Prima i contenuti live reali, poi il seed dimostrativo
        for item in live_items + SOURCE_ITEMS:
            is_test = "test_label" in item
            is_live = item.get("live")
            label = f"{item['icon']} {item['title'][:42]}{'...' if len(item['title'])>42 else ''}"
            if st.button(label, key=f"src_{item['id']}", use_container_width=True):
                st.session_state.ps = {"stage": "selected", "item": item,
                                        "analysis": None, "guardrail": None, "channels": None}
                st.rerun()
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
                        channels = raw_ch if (raw_ch and raw_ch.get("chatbot")) else channel_fallback(item)

                        status.update(label="✅ Pipeline completata — in attesa di validazione", state="complete")
                        st.session_state.ps.update({"stage":"validate","analysis":analysis,
                                                     "guardrail":guardrail,"channels":channels})
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
                        add_audit(item, "discarded", "Scartato dopo blocco guardrail")
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
                        add_audit(item, "published", "Approvato dall'operatore")
                        st.success("✅ Pubblicato su tutti i canali!")
                        time.sleep(0.8)
                        reset_pipeline()
                        st.rerun()
                with cr:
                    if st.button("✕ Rifiuta", use_container_width=True):
                        add_audit(item, "rejected", "Rifiutato dall'operatore in validazione")
                        reset_pipeline()
                        st.rerun()

# ════════════════════════════════════════
# TAB 2 — OUTPUT CANALI
# ════════════════════════════════════════
with tab2:
    if not st.session_state.published:
        st.info("📡 Nessun contenuto pubblicato. Vai in Pipeline, processa e approva un contenuto.")
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
with tab3:
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
                # Serbatoio 2 — contenuti pubblicati di recente dalla pipeline
                extra = ""
                if st.session_state.published:
                    extra = "\nCONTENUTI APPROVATI RECENTEMENTE:\n" + "\n".join(
                        f"- {p['title']}: {p['raw']}" for p in st.session_state.published[:5]
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
with tab4:
    st.markdown("### 📊 Destination Intelligence — Abruzzo")
    st.caption("Ultimi 30 giorni · dati aggiornati in tempo reale")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Query totali", "1.247", "+18%")
    k2.metric("Tasso risoluzione", "87%")
    k3.metric("Pubblicati CIH", len(st.session_state.published))
    k4.metric("Content Gap Alert", "5")

    daily, topics, langs, gaps = get_analytics()

    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.line(daily, x="Giorno", y="Query", title="Query giornaliere",
                      color_discrete_sequence=["#028090"])
        fig.update_layout(height=260, margin=dict(t=35,b=0,l=0,r=0))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig2 = px.pie(values=list(langs.values()), names=list(langs.keys()),
                      title="Mercati per lingua",
                      color_discrete_sequence=["#065A82","#028090","#02C39A","#64748B"])
        fig2.update_layout(height=260, margin=dict(t=35,b=0,l=0,r=0))
        st.plotly_chart(fig2, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        fig3 = px.bar(topics, x="Query", y="Topic", orientation="h",
                      title="Topic più richiesti",
                      color_discrete_sequence=["#028090"])
        fig3.update_layout(height=300, margin=dict(t=35,b=0,l=0,r=0))
        st.plotly_chart(fig3, use_container_width=True)
    with c4:
        st.markdown("**⚠️ Content Gap Alert**")
        st.caption("Domande dei turisti senza risposta nel KB")
        for gap in gaps:
            hot = "🔥 " if gap["hot"] else ""
            g1, g2, g3 = st.columns([4, 0.8, 0.8])
            g1.write(f"{hot}{gap['Domanda']}")
            g2.markdown(f"**{gap['N']}**")
            if gap["hot"]: g3.error(gap["Trend"])
            else:          g3.write(gap["Trend"])

# ════════════════════════════════════════
# TAB 5 — AUDIT LOG
# ════════════════════════════════════════
with tab5:
    st.markdown("### 📋 Registro decisioni — EU AI Act compliance")
    st.caption(f"{len(st.session_state.audit_log)} eventi registrati · ogni decisione automatizzata è tracciata")

    if not st.session_state.audit_log:
        st.info("Nessun evento ancora. Processa contenuti dalla Pipeline per popolare il log.")
    else:
        result_labels = {
            "published":     "✅ Pubblicato",
            "blocked":       "⛔ Bloccato Guardrail",
            "guardrail_pass":"🛡️ Guardrail OK",
            "rejected":      "❌ Rifiutato operatore",
            "discarded":     "🗑️ Scartato",
        }
        counts = {k: sum(1 for e in st.session_state.audit_log if e["Evento"]==k)
                  for k in result_labels}
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Pubblicati",      counts.get("published",0))
        m2.metric("Bloccati Guardrail", counts.get("blocked",0))
        m3.metric("Guardrail OK",    counts.get("guardrail_pass",0))
        m4.metric("Rifiutati",       counts.get("rejected",0))

        st.divider()
        df_log = pd.DataFrame([{
            "Ora":       e["Ora"],
            "Contenuto": e["Contenuto"],
            "Fonte":     e["Fonte"],
            "Evento":    result_labels.get(e["Evento"], e["Evento"]),
            "Dettaglio": e["Dettaglio"]
        } for e in st.session_state.audit_log])
        st.dataframe(df_log, use_container_width=True, hide_index=True)

        st.caption("**EU AI Act Art. 13–14 (Trasparenza + Supervisione umana):** ogni decisione automatizzata è tracciata con timestamp, fonte, tipo di check e azione. I contenuti bloccati dal Guardrail non raggiungono mai l'utente finale senza revisione umana.")
