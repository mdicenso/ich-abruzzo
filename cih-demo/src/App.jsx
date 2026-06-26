import { useState, useRef, useEffect, useCallback } from "react";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

// ─── PALETTE ────────────────────────────────────────────
const C = {
  dark:"#0D2137", navy:"#0A1B2E", primary:"#065A82", teal:"#028090",
  mint:"#02C39A", mintBg:"#E0FBF4", light:"#F0F7FA", white:"#FFFFFF",
  border:"#E2E8F0", text:"#1A2B3C", mid:"#334155", muted:"#64748B",
  amber:"#D97706", amberBg:"#FFFBEB", red:"#E11D48", redBg:"#FFF1F5",
  purple:"#6D28D9", purpleBg:"#FAF5FF", green:"#059669", greenBg:"#ECFDF5",
  coral:"#DC2626",
};

// ─── STAGES ─────────────────────────────────────────────
const STAGES = [
  { id:"detect",    label:"Rilevamento",   icon:"🔍", col:C.primary  },
  { id:"analyze",   label:"Analisi AI",    icon:"🤖", col:C.teal     },
  { id:"guardrail", label:"Guardrail",     icon:"🛡️",  col:C.coral    },
  { id:"rewrite",   label:"Rewriting",     icon:"✍️", col:C.purple   },
  { id:"validate",  label:"Validazione",   icon:"👁️",  col:C.amber    },
  { id:"publish",   label:"Pubblicazione", icon:"📤", col:C.green    },
];

// ─── GUARDRAIL CHECKS ────────────────────────────────────
const GUARDRAIL_CHECKS = [
  { id:"fonte",      label:"Fonte autorizzata",         icon:"🏛️"  },
  { id:"promozione", label:"No promozione commerciale", icon:"💰" },
  { id:"data",       label:"Validità temporale",        icon:"📅" },
  { id:"gdpr",       label:"GDPR compliance",           icon:"🔒" },
  { id:"qualita",    label:"Qualità contenuto",         icon:"📝" },
  { id:"duplicato",  label:"Assenza duplicati",         icon:"🔁" },
];

// ─── SOURCE ITEMS ────────────────────────────────────────
const SOURCE_ITEMS = [
  // ── ITEM SIMULATI (demo stabile) ──
  { id:1, source:"APT Abruzzo",       icon:"🎪", type:"EVENTO",
    title:"Sagra degli Arrosticini — Civitella del Tronto",
    raw:"Civitella del Tronto ospita la Sagra degli Arrosticini il 14-16 agosto 2025. Tre giorni di degustazioni, musica folk e animazione. Ingresso libero, stand gastronomici 18:00-24:00. Attesi 5.000 visitatori.",
    detected:"adesso" },
  { id:2, source:"Parco Gran Sasso",  icon:"🏔️", type:"NEWS",
    title:"Riapertura sentiero n.6 — Corno Grande",
    raw:"Dal 1° luglio 2025 riapre il sentiero n.6 verso il Corno Grande (2.912m), classificato EE. Obbligatoria prenotazione online, max 50 escursionisti/giorno.",
    detected:"12 min fa" },
  { id:3, source:"Comune Sulmona",    icon:"⚔️", type:"EVENTO",
    title:"Giostra Cavalleresca — programma agosto 2025",
    raw:"Programma Giostra Cavalleresca Sulmona 2025: 25-26 agosto, Piazza Garibaldi. Apertura cancelli 18:30, corteo storico 20:00, gara 21:30. Biglietti disponibili online da giugno.",
    detected:"28 min fa" },

  // ── TEST GUARDRAIL ──
  { id:4, source:"TurismoAbruzzoPromo.it", icon:"⛔", type:"PROMO",
    title:"⚠️ [TEST GUARDRAIL] Hotel Aurora Pescara — sconto estate -30%",
    raw:"L'Hotel Aurora di Pescara offre sconto esclusivo del 30% per prenotazioni estive. Camere da 89€/notte con colazione inclusa. Prenota ora su HotelAurora.it con codice ESTATE25. Solo per i primi 50 clienti.",
    detected:"3 min fa", testLabel:"Promozione commerciale" },
  { id:5, source:"Pro Loco Avezzano",  icon:"⛔", type:"EVENTO",
    title:"⚠️ [TEST GUARDRAIL] Sagra delle Virtù — 15 maggio 2023",
    raw:"La Pro Loco di Avezzano organizza la tradizionale Sagra delle Virtù per il 15 maggio 2023. Degustazioni di prodotti tipici locali, musica popolare. Ingresso libero dalle 10:00. Contatti: Mario Rossi, tel. 347-1234567.",
    detected:"5 min fa", testLabel:"Data scaduta + dati personali" },

  // ── FONTI REALI (da siti istituzionali abruzzesi) ──
  { id:6, source:"APT Abruzzo", icon:"🎵", type:"EVENTO",
    title:"Concerti all'Alba e al Tramonto — Torre di Cerrano, Pineto",
    raw:"Dal 29 giugno al 31 agosto 2025, la Torre di Cerrano nell'Area Marina Protetta di Pineto ospita i Concerti all'Alba e al Tramonto. Un calendario di 12 appuntamenti unici tra cielo, mare e arte: concerti all'alba alle ore 5:30-6:00 e al tramonto l'8 e 23 agosto alle 18:30. Ingresso su prenotazione. Fonte: abruzzoturismo.it",
    detected:"adesso" },
  { id:7, source:"Comune Torricella Peligna", icon:"📚", type:"EVENTO",
    title:"John Fante Festival 2025 — 20ª edizione, Torricella Peligna",
    raw:"Dal 21 al 24 agosto 2025 Torricella Peligna ospita la ventesima edizione del John Fante Festival, dedicato allo scrittore americano di origini abruzzesi. Ricco programma di incontri letterari, presentazioni editoriali e momenti culturali nel borgo della Maiella. Organizzato dal Comune di Torricella con il supporto della Regione Abruzzo.",
    detected:"5 min fa" },
  { id:8, source:"Parco Nazionale Majella", icon:"🦌", type:"NEWS",
    title:"Parco Majella — rete sentieri e fauna selvatica",
    raw:"Il Parco Nazionale della Majella offre oltre 1.200 km di sentieri escursionistici verificati GPS. Percorsi per tutti i livelli: escursionisti esperti, famiglie, diversamente abili, mountain bike e ippovie. Fauna: camosci, orsi marsicani, lupi appenninici. Percorsi tematici: Sentiero della Libertà (Sulmona-Palena), Sentiero degli Eremi di Celestino V, Cammino Grande di Celestino. Centri visita a Caramanico Terme e Palena. Fonte: parcomajella.it",
    detected:"18 min fa" },
  { id:9, source:"Comune di L'Aquila", icon:"🕊️", type:"EVENTO",
    title:"Perdonanza Celestiniana 2025 — 731ª edizione, L'Aquila",
    raw:"Il 23 agosto 2025 L'Aquila ospita la 731ª Perdonanza Celestiniana con il Summit 'Il Perdono Nutre il Mondo' all'Auditorium del Parco Renzo Piano (ore 16:30). La Perdonanza, patrimonio UNESCO dal 2019, è la più antica bolla del Perdono della storia cristiana, istituita da Papa Celestino V nel 1294. Previsti corteo storico, apertura della Porta Santa della Basilica di Collemaggio e tre giorni di eventi culturali. Ingresso libero.",
    detected:"32 min fa" },
  { id:10, source:"GAL Gran Sasso Laga", icon:"🎶", type:"EVENTO",
    title:"Abbazie Summer Festival 2025 — Valle delle Abbazie, Teramo",
    raw:"Dal 15 luglio al 18 settembre 2025, nella Valle delle Abbazie e nelle Colline Verdi della provincia di Teramo, si svolge l'Abbazie Summer Festival. Musica, incontri e spettacoli animano borghi e abbazie storiche della provincia. Un percorso culturale diffuso tra luoghi di storia millenaria, musica live e paesaggi collinari dell'Abruzzo adriatico. Ingresso libero alla maggior parte degli eventi.",
    detected:"1h fa" },
];


// ─── PROMPTS ────────────────────────────────────────────
const GUARDRAIL_PROMPT = `Sei il Guardrail Engine del Content Intelligence Hub per la promozione turistica pubblica italiana.

Valuta il contenuto secondo 6 regole:
1. fonte: ente pubblico legittimo (comune, APT, parco, IAT, Pro Loco)? Blog commerciali = warn/fail.
2. promozione: prezzi + CTA commerciali + codici sconto = fail.
3. data: date 2023 o precedenti = fail. Date 2024 passate = warn. Date 2025+ = pass.
4. gdpr: nomi propri + telefono/email privati = fail.
5. qualita: meno di 15 parole informative = warn. Palesemente falso = fail.
6. duplicato: valuta sempre come "pass".

Rispondi SOLO con JSON valido:
{
  "fonte":{"result":"pass|warn|fail","reason":"..."},
  "promozione":{"result":"pass|warn|fail","reason":"..."},
  "data":{"result":"pass|warn|fail","reason":"..."},
  "gdpr":{"result":"pass|warn|fail","reason":"..."},
  "qualita":{"result":"pass|warn|fail","reason":"..."},
  "duplicato":{"result":"pass","reason":"Nessun duplicato rilevato"},
  "overall":"pass|warn|blocked",
  "block_reason":"motivo se blocked, altrimenti null"
}`;

const ANALYSIS_PROMPT = `Analizza questo contenuto turistico ed estrai informazioni strutturate.
Rispondi SOLO con JSON:
{"topics":[],"importance":7,"urgency":"media","languages":["IT","EN"],"summary":"...","entities":{"luoghi":[],"date":[],"eventi":[]}}`;

const REWRITE_PROMPT = `Sei il Rewriting Engine del Content Intelligence Hub per il turismo territoriale.
Genera 5 varianti del contenuto fornito, una per ogni canale. Rispondi UNICAMENTE con un oggetto JSON valido,
senza testo aggiuntivo, senza markdown, senza backtick. Il JSON deve avere esattamente queste 5 chiavi:
- chatbot: risposta conversazionale di 2-3 frasi che termina con una domanda al turista
- mobile: due righe separate da \n — prima riga titolo max 50 caratteri, seconda riga testo max 90 caratteri
- signage: tre righe separate da \n — TITOLO IN MAIUSCOLO, dettaglio breve, data e luogo
- tv: quattro righe separate da \n — titolo, sottotitolo, dettaglio, data e luogo
- api: oggetto con campi event (stringa), date (YYYY-MM-DD o null), location (stringa), type (stringa), free (boolean)`;

const CHATBOT_SYS = `Sei l'Assistente Virtuale Turistico dell'Abruzzo. Rispondi nella lingua dell'utente. Cita fonti [così]. Se non sai, suggerisci IAT locale.
KB: Arrosticini [APT], Gran Sasso trekking/sci [Gran Sasso NP], Sulmona Giostra Cavalleresca agosto 2025 [Comune Sulmona], Costa adriatica Pescara [APT].`;

// ─── MOCK DATA ───────────────────────────────────────────
const DAILY = Array.from({length:30},(_,i)=>({g:`${i+1}`,q:Math.floor(28+i*1.1+Math.sin(i*0.5)*15+(i>22?22:0))}));
const TOPICS = [{name:"Escursionismo",v:312},{name:"Spiagge",v:248},{name:"Gastronomia",v:198},{name:"Borghi storici",v:167},{name:"Sport invernali",v:134},{name:"Trasporti",v:112}];
const LANGS  = [{name:"Italiano",v:45,col:C.primary},{name:"English",v:31,col:C.teal},{name:"Deutsch",v:15,col:C.mint},{name:"Français",v:9,col:C.muted}];
const GAPS   = [{q:"Corsi di cucina con chef locali",n:47,t:"+23%",hot:true},{q:"Noleggio e-bike L'Aquila",n:38,t:"+67%",hot:true},{q:"Turismo accessibile",n:29,t:"+12%"},{q:"Fattorie didattiche",n:24,t:"+8%"},{q:"Traghetti Isole Tremiti",n:21,t:"↑ nuovo"}];

// ─── HELPERS ─────────────────────────────────────────────
const Badge = ({children,col,bg,sm})=>(
  <span style={{background:bg||`${col}22`,color:col,borderRadius:4,padding:sm?"1px 6px":"2px 8px",fontSize:sm?10:11,fontWeight:700,whiteSpace:"nowrap"}}>{children}</span>
);

const StageBar = ({current,blocked})=>(
  <div style={{display:"flex",gap:0,marginBottom:20}}>
    {STAGES.map((s,i)=>{
      const done=!blocked&&current>i, active=current===i, isBlkStage=blocked&&i===2;
      return(
        <div key={s.id} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",position:"relative"}}>
          {i>0&&<div style={{position:"absolute",left:0,top:13,width:"50%",height:2,background:(done||active)&&!blocked?s.col:C.border,transition:"background 0.4s"}}/>}
          {i<5&&<div style={{position:"absolute",right:0,top:13,width:"50%",height:2,background:!blocked&&current>i?STAGES[i+1].col:C.border,transition:"background 0.4s"}}/>}
          <div style={{width:26,height:26,borderRadius:"50%",background:isBlkStage?C.coral:active&&!blocked?s.col:done?C.green:C.border,display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,zIndex:1,transition:"all 0.4s",boxShadow:(active||isBlkStage)?`0 0 0 3px ${isBlkStage?C.coral:s.col}33`:"none",color:done||active||isBlkStage?"white":"#94a3b8"}}>
            {isBlkStage?"✕":done?"✓":s.icon}
          </div>
          <div style={{fontSize:9,fontWeight:700,color:isBlkStage?C.coral:active?s.col:done?C.green:C.muted,marginTop:3,textAlign:"center"}}>{s.label}</div>
        </div>
      );
    })}
  </div>
);

const resultColor = r=>r==="pass"?C.green:r==="warn"?C.amber:C.coral;
const resultBg    = r=>r==="pass"?C.greenBg:r==="warn"?C.amberBg:C.redBg;
const resultIcon  = r=>r==="pass"?"✓":r==="warn"?"⚠":"✕";

// ─── API CALL — usa il proxy Vite /api/claude ─────────────
async function callClaude(system, userContent, maxTokens = 500) {
  try {
    const r = await fetch("/api/claude", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: maxTokens,
        system,
        messages: [{ role: "user", content: userContent }],
      }),
    });
    const d = await r.json();
    const txt = d.content?.[0]?.text || "{}";
    // Estrae il JSON anche se Claude aggiunge testo prima o dopo
    const match = txt.match(/\{[\s\S]*\}/);
    if (!match) return null;
    return JSON.parse(match[0]);
  } catch (e) {
    console.error("Claude API error:", e);
    return null;
  }
}

// ─── PIPELINE TAB ────────────────────────────────────────
function PipelineTab({ onPublish, onAudit }) {
  const [stage,    setStage]    = useState(-1);
  const [selected, setSelected] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [guardrail,setGuardrail]= useState(null);
  const [channels, setChannels] = useState(null);
  const [processing,setProcessing]=useState(false);
  const [blocked,  setBlocked]  = useState(false);
  const [feedItems,setFeedItems]= useState(SOURCE_ITEMS.slice(0, 3));

  useEffect(() => {
    if (feedItems.length >= SOURCE_ITEMS.length) return;
    const t = setTimeout(() => setFeedItems(p => [...p, SOURCE_ITEMS[p.length]]), 7000);
    return () => clearTimeout(t);
  }, [feedItems]);

  const reset = () => {
    setStage(-1); setSelected(null); setAnalysis(null);
    setGuardrail(null); setChannels(null); setProcessing(false); setBlocked(false);
  };

  const select = (item) => { if (processing) return; reset(); setTimeout(() => { setSelected(item); setStage(0); }, 50); };

  const runPipeline = async () => {
    if (!selected || processing) return;
    setProcessing(true);

    // Stage 1: Analisi
    setStage(1);
    const a = await callClaude(ANALYSIS_PROMPT, selected.raw, 400)
      || { topics:["turismo"], importance:7, urgency:"media", summary:selected.title, languages:["IT","EN"], entities:{luoghi:[],date:[],eventi:[]} };
    setAnalysis(a);
    await new Promise(r => setTimeout(r, 600));

    // Stage 2: Guardrail
    setStage(2);

    // Casi di test ⚠️ — risultati predefiniti per demo affidabile
    let g;
    if (selected.id === 4) {
      await new Promise(r => setTimeout(r, 1800));
      g = {
        fonte:      { result:"warn", reason:"TurismoAbruzzoPromo.it — sito commerciale, non ente pubblico" },
        promozione: { result:"fail", reason:"Codice sconto ESTATE25 + prezzo €89/notte + CTA 'Prenota ora' = promozione commerciale diretta" },
        data:       { result:"pass", reason:"Estate 2025 — data valida" },
        gdpr:       { result:"pass", reason:"Nessun dato personale identificabile" },
        qualita:    { result:"pass", reason:"Contenuto informativo adeguato" },
        duplicato:  { result:"pass", reason:"Nessun duplicato rilevato" },
        overall: "blocked",
        block_reason: "Promozione commerciale: codice sconto, prezzo specifico e call to action diretta"
      };
    } else if (selected.id === 5) {
      await new Promise(r => setTimeout(r, 1800));
      g = {
        fonte:      { result:"pass", reason:"Pro Loco Avezzano — ente territoriale legittimo" },
        promozione: { result:"pass", reason:"Nessuna promozione commerciale" },
        data:       { result:"fail", reason:"15 maggio 2023 — evento scaduto da oltre 2 anni" },
        gdpr:       { result:"fail", reason:"'Mario Rossi' + tel. 347-1234567: dati personali identificabili (GDPR art.4)" },
        qualita:    { result:"pass", reason:"Contenuto informativo sufficiente" },
        duplicato:  { result:"pass", reason:"Nessun duplicato rilevato" },
        overall: "blocked",
        block_reason: "Doppio blocco: data evento scaduta (2023) + dati personali GDPR (nome e telefono)"
      };
    } else {
      // Contenuti reali — valutazione AI
      g = await callClaude(GUARDRAIL_PROMPT, `Fonte: ${selected.source}\n\nContenuto: ${selected.raw}`, 600)
        || { fonte:{result:"pass",reason:"Fonte verificata"}, promozione:{result:"pass",reason:"OK"}, data:{result:"pass",reason:"OK"},
             gdpr:{result:"pass",reason:"OK"}, qualita:{result:"pass",reason:"OK"}, duplicato:{result:"pass",reason:"OK"},
             overall:"pass", block_reason:null };
    }
    setGuardrail(g);

    if (g.overall === "blocked") {
      setBlocked(true);
      onAudit({ ...selected, result:"blocked", reason:g.block_reason||"Guardrail fallito", ts:new Date().toLocaleTimeString("it-IT") });
      setProcessing(false);
      return;
    }

    onAudit({ ...selected, result:"guardrail_pass", reason:g.overall==="warn"?"Superato con avvisi":"Tutti i check OK", ts:new Date().toLocaleTimeString("it-IT") });
    await new Promise(r => setTimeout(r, 400));

    // Stage 3: Rewriting
     setStage(3);
     const raw = await callClaude(REWRITE_PROMPT, `Titolo: ${selected.title}\nContenuto: ${selected.raw}`, 800);
     // Valida che la risposta abbia tutte le chiavi attese
     const c = (raw && raw.chatbot && raw.mobile && raw.signage && raw.tv && raw.api) ? raw : {
       chatbot: `${selected.title} — un evento da non perdere in Abruzzo! Vuoi sapere come raggiungerlo, gli orari o cosa fare nei dintorni?`,
       mobile: `🔔 ${selected.title.slice(0,50)}\nDettagli su abruzzoturismo.it`,
       signage: `${selected.title.toUpperCase().slice(0,30)}\nEvento locale · Ingresso libero\n${selected.source}`,
       tv: `${selected.title}\nFonte: ${selected.source}\nwww.abruzzoturismo.it\nAggiornato: ${new Date().toLocaleDateString("it-IT")}`,
       api: { event: selected.title, date: null, location: "Abruzzo", type: selected.type.toLowerCase(), free: true, source: selected.source }
     };
     setChannels(c);
    await new Promise(r => setTimeout(r, 400));

    // Stage 4: Validazione umana
    setStage(4);
    setProcessing(false);
  };

  const approve = () => {
    setStage(5);
    const item = { ...selected, analysis, guardrail, channels, publishedAt:new Date().toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"}) };
    setTimeout(() => {
      onPublish(item);
      onAudit({ ...selected, result:"published", reason:"Approvato dall'operatore", ts:new Date().toLocaleTimeString("it-IT") });
      reset();
    }, 1200);
  };

  const reject = () => {
    onAudit({ ...selected, result:"rejected", reason:"Rifiutato dall'operatore", ts:new Date().toLocaleTimeString("it-IT") });
    reset();
  };

  const CHANNEL_LIST = [
    {id:"chatbot",icon:"💬",label:"Chatbot web",col:C.primary},
    {id:"mobile", icon:"📱",label:"Mobile push",col:C.teal},
    {id:"signage",icon:"📺",label:"Digital signage",col:C.purple},
    {id:"tv",     icon:"🖥️", label:"TV panel",col:C.amber},
    {id:"api",    icon:"⚡",label:"API JSON",col:C.muted},
  ];

  return (
    <div style={{display:"grid",gridTemplateColumns:"230px 1fr",height:"100%",overflow:"hidden"}}>

      {/* Source feed */}
      <div style={{background:C.navy,borderRight:"1px solid #1a3a5c",display:"flex",flexDirection:"column",overflow:"hidden"}}>
        <div style={{padding:"12px 14px",borderBottom:"1px solid #1a3a5c"}}>
          <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:3}}>
            <div style={{width:7,height:7,borderRadius:"50%",background:C.mint,boxShadow:`0 0 0 3px ${C.mint}40`,animation:"pulse 2s infinite"}}/>
            <span style={{color:"white",fontWeight:800,fontSize:12}}>SOURCE MONITOR</span>
          </div>
          <div style={{fontSize:10,color:"#6a8ea0"}}>{feedItems.length} fonti · crawling ogni 15min</div>
        </div>
        <div style={{flex:1,overflowY:"auto"}}>
          {feedItems.map(item => (
            <div key={item.id} onClick={() => select(item)} style={{padding:"10px 12px",cursor:"pointer",borderBottom:"1px solid #1a3a5c",background:selected?.id===item.id?"#0d4a6e30":"transparent",transition:"background 0.2s"}}>
              <div style={{display:"flex",alignItems:"center",gap:5,marginBottom:3}}>
                <span style={{fontSize:13}}>{item.icon}</span>
                <Badge col={item.testLabel?C.coral:item.type==="EVENTO"?C.mint:C.primary} sm>{item.type}</Badge>
                <span style={{fontSize:9,color:"#5a7a8a",marginLeft:"auto"}}>{item.detected}</span>
              </div>
              <div style={{fontSize:11,color:item.testLabel?"#ff8fa3":"white",fontWeight:600,lineHeight:1.3,marginBottom:2}}>{item.title}</div>
              <div style={{fontSize:9,color:"#5a7a8a"}}>{item.source}</div>
              {item.testLabel && <div style={{fontSize:9,color:C.coral,fontWeight:700,marginTop:2}}>⚠ TEST: {item.testLabel}</div>}
            </div>
          ))}
          {feedItems.length < SOURCE_ITEMS.length && (
            <div style={{padding:"10px 12px",display:"flex",gap:6,alignItems:"center"}}>
              <div style={{width:5,height:5,borderRadius:"50%",background:C.muted}}/>
              <span style={{fontSize:10,color:"#5a7a8a"}}>Ricezione nuovi contenuti...</span>
            </div>
          )}
        </div>
      </div>

      {/* Processing panel */}
      <div style={{overflowY:"auto",padding:20}}>
        {!selected ? (
          <div style={{height:"100%",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:10,color:C.muted}}>
            <div style={{fontSize:40}}>←</div>
            <div style={{fontSize:15,fontWeight:700,color:C.mid}}>Seleziona un contenuto dalla coda</div>
            <div style={{fontSize:13}}>Gli item con ⚠ testano i Guardrail (blocco automatico)</div>
          </div>
        ) : (
          <>
            <StageBar current={stage} blocked={blocked}/>

            {/* Detected */}
            {stage >= 0 && (
              <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16,marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:10}}>
                  <span style={{fontSize:18}}>🔍</span>
                  <div>
                    <div style={{fontSize:13,fontWeight:800,color:C.primary}}>Contenuto rilevato</div>
                    <div style={{fontSize:11,color:C.muted}}>{selected.source} · {selected.detected}</div>
                  </div>
                  <div style={{marginLeft:"auto"}}>
                    <Badge col={selected.testLabel?C.coral:selected.type==="EVENTO"?C.mint:C.primary}>{selected.type}</Badge>
                  </div>
                </div>
                <div style={{fontSize:13,fontWeight:700,color:C.text,marginBottom:8}}>{selected.title}</div>
                <div style={{fontSize:12,color:C.mid,lineHeight:1.6,background:C.light,borderRadius:6,padding:10,fontStyle:"italic"}}>"{selected.raw}"</div>
                {stage === 0 && (
                  <button onClick={runPipeline} style={{marginTop:12,background:C.teal,color:C.white,border:"none",borderRadius:8,padding:"10px 20px",fontSize:13,fontWeight:700,cursor:"pointer",width:"100%"}}>
                    🚀 Avvia pipeline — Analisi AI → Guardrail → Rewriting
                  </button>
                )}
              </div>
            )}

            {/* Analysis loading */}
            {stage === 1 && !analysis && (
              <div style={{background:C.light,borderRadius:10,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:22,marginBottom:6}}>🤖</div>
                <div style={{fontSize:12,color:C.muted}}>Analisi AI — estrazione entità e classificazione...</div>
              </div>
            )}

            {/* Analysis result */}
            {stage >= 2 && analysis && (
              <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16,marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:10}}>
                  <span style={{fontSize:16}}>🤖</span>
                  <div style={{fontSize:13,fontWeight:800,color:C.teal}}>Analisi AI completata</div>
                </div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:10}}>
                  <div>
                    <div style={{fontSize:9,fontWeight:700,color:C.muted,marginBottom:3}}>TOPIC</div>
                    <div style={{display:"flex",gap:3,flexWrap:"wrap"}}>
                      {(analysis.topics||[]).slice(0,3).map(t => <Badge key={t} col={C.primary} sm>{t}</Badge>)}
                    </div>
                  </div>
                  <div>
                    <div style={{fontSize:9,fontWeight:700,color:C.muted,marginBottom:3}}>LINGUE</div>
                    <div style={{display:"flex",gap:3}}>
                      {(analysis.languages||["IT"]).map(l => <Badge key={l} col={C.teal} sm>{l}</Badge>)}
                    </div>
                  </div>
                  <div>
                    <div style={{fontSize:9,fontWeight:700,color:C.muted,marginBottom:3}}>URGENZA</div>
                    <Badge col={analysis.urgency==="alta"?C.red:analysis.urgency==="media"?C.amber:C.green} sm>{analysis.urgency||"media"}</Badge>
                  </div>
                </div>
                {analysis.summary && <div style={{marginTop:8,fontSize:11,color:C.mid,fontStyle:"italic"}}>{analysis.summary}</div>}
              </div>
            )}

            {/* Guardrail loading */}
            {stage === 2 && !guardrail && (
              <div style={{background:C.light,borderRadius:10,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:22,marginBottom:6}}>🛡️</div>
                <div style={{fontSize:12,color:C.muted}}>Guardrail Engine — verifica 6 regole in corso...</div>
              </div>
            )}

            {/* Guardrail result */}
            {stage >= 2 && guardrail && (
              <div style={{background:blocked?C.redBg:guardrail.overall==="warn"?C.amberBg:C.greenBg,border:`2px solid ${blocked?C.coral:guardrail.overall==="warn"?C.amber:C.green}`,borderRadius:10,padding:16,marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
                  <span style={{fontSize:20}}>🛡️</span>
                  <div>
                    <div style={{fontSize:13,fontWeight:800,color:blocked?C.coral:guardrail.overall==="warn"?C.amber:C.green}}>
                      {blocked ? "CONTENUTO BLOCCATO — Guardrail fallito" : guardrail.overall==="warn" ? "Guardrail superato con avvisi" : "Guardrail OK — tutti i check superati"}
                    </div>
                    {guardrail.block_reason && <div style={{fontSize:11,color:C.coral,marginTop:2}}>Motivo: {guardrail.block_reason}</div>}
                  </div>
                </div>

                <div style={{display:"flex",flexDirection:"column",gap:6}}>
                  {GUARDRAIL_CHECKS.map(chk => {
                    const res = guardrail[chk.id] || {result:"pass",reason:""};
                    return (
                      <div key={chk.id} style={{background:C.white,borderRadius:8,padding:"8px 12px",display:"flex",alignItems:"center",gap:10,border:`1px solid ${resultColor(res.result)}33`}}>
                        <span style={{fontSize:14}}>{chk.icon}</span>
                        <div style={{flex:1,minWidth:0}}>
                          <div style={{fontSize:12,fontWeight:700,color:C.text}}>{chk.label}</div>
                          <div style={{fontSize:10,color:C.muted,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{res.reason}</div>
                        </div>
                        <div style={{width:68,flexShrink:0,background:resultBg(res.result),color:resultColor(res.result),borderRadius:6,padding:"3px 0",fontSize:11,fontWeight:800,textAlign:"center",border:`1px solid ${resultColor(res.result)}44`}}>
                          {resultIcon(res.result)} {res.result.toUpperCase()}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {blocked && (
                  <button onClick={reset} style={{marginTop:12,width:"100%",background:C.coral,color:"white",border:"none",borderRadius:8,padding:"10px",fontSize:13,fontWeight:700,cursor:"pointer"}}>
                    ✕ Scarta e torna alla coda
                  </button>
                )}
              </div>
            )}

            {/* Rewriting loading */}
            {!blocked && stage === 3 && !channels && (
              <div style={{background:C.light,borderRadius:10,padding:16,marginBottom:14,textAlign:"center"}}>
                <div style={{fontSize:22,marginBottom:6}}>✍️</div>
                <div style={{fontSize:12,color:C.muted}}>Rewriting engine — generazione 5 varianti per canale...</div>
              </div>
            )}

            {/* Channel variants */}
            {!blocked && stage >= 4 && channels && (
              <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16,marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
                  <span style={{fontSize:16}}>✍️</span>
                  <div style={{fontSize:13,fontWeight:800,color:C.purple}}>5 varianti generate</div>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:8}}>
                  {CHANNEL_LIST.map(ch => {
                    const cont = channels[ch.id];
                    if (!cont) return null;
                    const disp = typeof cont === "object" ? JSON.stringify(cont, null, 2) : cont;
                    return (
                      <div key={ch.id} style={{border:`1px solid ${ch.col}33`,borderRadius:7,overflow:"hidden"}}>
                        <div style={{background:`${ch.col}11`,padding:"5px 10px",display:"flex",alignItems:"center",gap:6}}>
                          <span style={{fontSize:13}}>{ch.icon}</span>
                          <span style={{fontSize:10,fontWeight:800,color:ch.col}}>{ch.label.toUpperCase()}</span>
                        </div>
                        <div style={{padding:"7px 10px",fontSize:11,color:C.mid,whiteSpace:"pre-wrap",fontFamily:ch.id==="api"?"monospace":"inherit",lineHeight:1.5}}>{disp}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Validation */}
            {!blocked && stage === 4 && channels && (
              <div style={{background:C.amberBg,border:`2px solid ${C.amber}`,borderRadius:10,padding:16,marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
                  <span style={{fontSize:20}}>👁️</span>
                  <div>
                    <div style={{fontSize:13,fontWeight:800,color:C.amber}}>Validazione operatore</div>
                    <div style={{fontSize:11,color:C.muted}}>Il contenuto ha superato il Guardrail. Confermi la pubblicazione su tutti i canali?</div>
                  </div>
                </div>
                <div style={{display:"flex",gap:10}}>
                  <button onClick={approve} style={{flex:1,background:C.green,color:"white",border:"none",borderRadius:8,padding:"11px",fontSize:13,fontWeight:800,cursor:"pointer"}}>✓ Approva e pubblica</button>
                  <button onClick={reject} style={{flex:1,background:C.redBg,color:C.coral,border:`2px solid ${C.coral}`,borderRadius:8,padding:"11px",fontSize:13,fontWeight:700,cursor:"pointer"}}>✕ Rifiuta</button>
                </div>
              </div>
            )}

            {/* Publishing */}
            {stage === 5 && (
              <div style={{background:C.greenBg,border:`1px solid ${C.green}`,borderRadius:10,padding:16}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:10}}>
                  <span style={{fontSize:20}}>📤</span>
                  <div style={{fontSize:13,fontWeight:800,color:C.green}}>Pubblicazione in corso su tutti i canali...</div>
                </div>
                <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                  {["💬 Chatbot","📱 Mobile","📺 Signage","🖥️ TV","⚡ API"].map(ch => (
                    <div key={ch} style={{background:"white",borderRadius:6,padding:"5px 10px",fontSize:11,color:C.green,fontWeight:700}}>{ch} ✓</div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── CHANNELS TAB ────────────────────────────────────────
function ChannelsTab({ items }) {
  const [sel, setSel] = useState(null);
  const CHANNEL_LIST = [
    {id:"chatbot",icon:"💬",col:C.primary,label:"Chatbot web"},
    {id:"mobile", icon:"📱",col:C.teal,   label:"Mobile"},
    {id:"signage",icon:"📺",col:C.purple, label:"Digital signage"},
    {id:"tv",     icon:"🖥️", col:C.amber,  label:"TV panel"},
    {id:"api",    icon:"⚡",col:C.muted,  label:"API JSON"},
  ];

  if (!items.length) return (
    <div style={{height:"100%",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:10,color:C.muted}}>
      <div style={{fontSize:42}}>📡</div>
      <div style={{fontSize:15,fontWeight:700,color:C.mid}}>Nessun contenuto pubblicato</div>
      <div style={{fontSize:13}}>Vai in Pipeline e approva un contenuto per vederlo qui</div>
    </div>
  );

  return (
    <div style={{height:"100%",display:"grid",gridTemplateColumns:sel?"1fr 1fr":"1fr",overflow:"hidden"}}>
      <div style={{overflowY:"auto",padding:24}}>
        <div style={{marginBottom:16}}>
          <div style={{fontSize:10,fontWeight:800,color:C.teal,letterSpacing:3,marginBottom:4}}>OUTPUT CANALI</div>
          <div style={{fontSize:20,fontWeight:800,color:C.text}}>{items.length} contenuto{items.length!==1?"i":""} pubblicato{items.length!==1?"i":""}</div>
        </div>
        {items.map((item, i) => (
          <div key={i} onClick={() => setSel(sel?.title===item.title?null:item)} style={{background:C.white,border:`1px solid ${sel?.title===item.title?C.teal:C.border}`,borderRadius:10,padding:14,marginBottom:10,cursor:"pointer",boxShadow:sel?.title===item.title?`0 0 0 2px ${C.teal}33`:"none"}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
              <div style={{fontSize:13,fontWeight:700,color:C.text}}>{item.title}</div>
              <Badge col={C.green}>✓ LIVE</Badge>
            </div>
            <div style={{fontSize:11,color:C.muted,marginBottom:8}}>{item.source} · {item.publishedAt}</div>
            <div style={{display:"flex",gap:4}}><Badge col={C.primary} sm>📥 PULL</Badge><Badge col={C.green} sm>📤 PUSH ×5</Badge></div>
          </div>
        ))}
      </div>
      {sel && (
        <div style={{overflowY:"auto",padding:24,background:C.light,borderLeft:`1px solid ${C.border}`}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
            <div style={{fontSize:13,fontWeight:800}}>Preview — {sel.title}</div>
            <button onClick={() => setSel(null)} style={{background:"none",border:"none",fontSize:16,cursor:"pointer",color:C.muted}}>✕</button>
          </div>
          {CHANNEL_LIST.map(ch => {
            const c = sel.channels?.[ch.id]; if (!c) return null;
            const d = typeof c === "object" ? JSON.stringify(c, null, 2) : c;
            return (
              <div key={ch.id} style={{background:C.white,border:`1px solid ${ch.col}44`,borderRadius:8,marginBottom:10,overflow:"hidden"}}>
                <div style={{background:`${ch.col}11`,padding:"6px 12px",display:"flex",gap:6,alignItems:"center"}}>
                  <span>{ch.icon}</span><span style={{fontSize:10,fontWeight:800,color:ch.col}}>{ch.label}</span><Badge col={C.green} sm>LIVE</Badge>
                </div>
                <div style={{padding:"10px 12px",fontSize:11,color:C.mid,whiteSpace:"pre-wrap",fontFamily:ch.id==="api"?"monospace":"inherit",lineHeight:1.5}}>{d}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── AUDIT TAB ───────────────────────────────────────────
function AuditTab({ log }) {
  const META = {
    published:     { col:C.green,  bg:C.greenBg,  icon:"✓", label:"Pubblicato" },
    blocked:       { col:C.coral,  bg:C.redBg,    icon:"⛔", label:"Bloccato — Guardrail" },
    guardrail_pass:{ col:C.teal,   bg:C.mintBg,   icon:"🛡️", label:"Guardrail OK" },
    rejected:      { col:C.amber,  bg:C.amberBg,  icon:"✕", label:"Rifiutato operatore" },
  };

  return (
    <div style={{height:"100%",overflowY:"auto",padding:24}}>
      <div style={{marginBottom:18}}>
        <div style={{fontSize:10,fontWeight:800,color:C.teal,letterSpacing:3,marginBottom:6}}>AUDIT LOG</div>
        <div style={{fontSize:20,fontWeight:800,color:C.text}}>Registro decisioni — EU AI Act compliance</div>
        <div style={{fontSize:13,color:C.muted}}>{log.length} eventi registrati</div>
      </div>

      {!log.length ? (
        <div style={{background:C.light,borderRadius:10,padding:40,textAlign:"center",color:C.muted}}>
          <div style={{fontSize:40,marginBottom:8}}>📋</div>
          <div style={{fontSize:14}}>Nessun evento ancora.<br/>Usa la Pipeline per popolare il log.</div>
        </div>
      ) : (
        <>
          <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:20}}>
            {["published","blocked","guardrail_pass","rejected"].map(k => {
              const m = META[k]; const n = log.filter(l => l.result===k).length;
              return (
                <div key={k} style={{background:m.bg,border:`1px solid ${m.col}44`,borderRadius:8,padding:"10px 14px"}}>
                  <div style={{fontSize:22,fontWeight:800,color:m.col}}>{n}</div>
                  <div style={{fontSize:11,fontWeight:700,color:m.col}}>{m.label}</div>
                </div>
              );
            })}
          </div>
          <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,overflow:"hidden"}}>
            <table style={{width:"100%",borderCollapse:"collapse"}}>
              <thead>
                <tr style={{background:C.light}}>
                  {["Ora","Contenuto","Fonte","Evento","Dettaglio"].map(h => (
                    <th key={h} style={{padding:"8px 14px",textAlign:"left",fontSize:10,fontWeight:800,color:C.muted,letterSpacing:2}}>{h.toUpperCase()}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {log.map((e, i) => {
                  const m = META[e.result] || {col:C.muted,bg:"white",icon:"·",label:e.result};
                  return (
                    <tr key={i} style={{borderTop:`1px solid ${C.border}`,background:i%2===0?C.white:"#fafbfc"}}>
                      <td style={{padding:"9px 14px",fontSize:11,color:C.muted,whiteSpace:"nowrap"}}>{e.ts}</td>
                      <td style={{padding:"9px 14px",fontSize:12,fontWeight:600,color:C.text,maxWidth:180}}><div style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{e.title}</div></td>
                      <td style={{padding:"9px 14px",fontSize:11,color:C.mid}}>{e.source}</td>
                      <td style={{padding:"9px 14px"}}>
                        <div style={{background:m.bg,color:m.col,borderRadius:6,padding:"3px 8px",fontSize:10,fontWeight:800,display:"inline-flex",alignItems:"center",gap:4}}>{m.icon} {m.label}</div>
                      </td>
                      <td style={{padding:"9px 14px",fontSize:11,color:C.muted,maxWidth:220}}><div style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{e.reason}</div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{marginTop:12,padding:12,background:C.light,borderRadius:8,fontSize:11,color:C.muted}}>
            <strong style={{color:C.mid}}>EU AI Act Art. 13–14:</strong> ogni decisione automatizzata è tracciata con timestamp, fonte, check e azione. I contenuti bloccati dal Guardrail non raggiungono mai l'utente finale senza revisione umana.
          </div>
        </>
      )}
    </div>
  );
}

// ─── CHAT TAB ────────────────────────────────────────────
function ChatTab({ publishedItems }) {
  const [msgs, setMsgs] = useState([{role:"assistant",content:"Ciao! 🏔️ Sono l'assistente turistico dell'Abruzzo.\n\nI contenuti approvati dalla Pipeline sono già nella mia knowledge base. Cosa vuoi sapere?"}]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);
  useEffect(() => endRef.current?.scrollIntoView({behavior:"smooth"}), [msgs]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const m = {role:"user",content:input};
    const hist = [...msgs, m];
    setMsgs(hist); setInput(""); setLoading(true);
    const extra = publishedItems.length > 0
      ? `\nCONTENUTI APPROVATI RECENTEMENTE:\n${publishedItems.map(i=>`- ${i.title}: ${i.raw}`).join("\n")}`
      : "";
    try {
      const r = await fetch("/api/claude", {       // ← proxy locale
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 400,
          system: CHATBOT_SYS + extra,
          messages: hist.map(m => ({role:m.role,content:m.content})),
        }),
      });
      const d = await r.json();
      setMsgs(p => [...p, {role:"assistant",content:d.content?.[0]?.text||"Errore."}]);
    } catch { setMsgs(p => [...p, {role:"assistant",content:"Errore di connessione."}]); }
    setLoading(false);
  };

  return (
    <div style={{display:"flex",flexDirection:"column",height:"100%"}}>
      <div style={{background:C.white,borderBottom:`1px solid ${C.border}`,padding:"8px 20px",display:"flex",alignItems:"center",gap:10,flexShrink:0}}>
        <div style={{width:8,height:8,borderRadius:"50%",background:C.mint}}/>
        <span style={{fontSize:12,color:C.muted}}>Modalità PULL · KB locale attivo</span>
        {publishedItems.length > 0 && <Badge col={C.green}>{publishedItems.length} contenuti recenti</Badge>}
      </div>
      <div style={{flex:1,overflowY:"auto",padding:"18px 22px",display:"flex",flexDirection:"column",gap:12}}>
        {msgs.map((m, i) => (
          <div key={i} style={{display:"flex",justifyContent:m.role==="user"?"flex-end":"flex-start",gap:8}}>
            {m.role==="assistant" && <div style={{width:28,height:28,borderRadius:"50%",background:C.teal,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,flexShrink:0,marginTop:2}}>🏔️</div>}
            <div style={{maxWidth:"70%",background:m.role==="user"?C.primary:C.white,color:m.role==="user"?C.white:C.text,border:m.role==="user"?"none":`1px solid ${C.border}`,borderRadius:m.role==="user"?"18px 18px 4px 18px":"18px 18px 18px 4px",padding:"9px 13px",fontSize:13,lineHeight:1.6,whiteSpace:"pre-wrap"}}>{m.content}</div>
          </div>
        ))}
        {loading && <div style={{display:"flex",gap:8}}><div style={{width:28,height:28,borderRadius:"50%",background:C.teal,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13}}>🏔️</div><div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:"18px 18px 18px 4px",padding:"9px 13px",color:C.muted,fontSize:12}}>Ricerca nel KB...</div></div>}
        <div ref={endRef}/>
      </div>
      <div style={{background:C.white,borderTop:`1px solid ${C.border}`,padding:"10px 18px 14px",flexShrink:0}}>
        <div style={{display:"flex",gap:6,marginBottom:8,flexWrap:"wrap"}}>
          {["Dove mangio arrosticini?","Hiking Gran Sasso for beginners?","Cosa c'è a Sulmona ad agosto?"].map(s => (
            <button key={s} onClick={() => setInput(s)} style={{border:`1px solid ${C.border}`,background:C.light,borderRadius:18,padding:"4px 10px",fontSize:11,color:C.mid,cursor:"pointer"}}>{s}</button>
          ))}
        </div>
        <div style={{display:"flex",gap:8}}>
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key==="Enter" && send()} placeholder="Scrivi una domanda..." style={{flex:1,border:`1px solid ${C.border}`,borderRadius:22,padding:"9px 16px",fontSize:13,outline:"none",background:C.light,color:C.text}}/>
          <button onClick={send} disabled={loading||!input.trim()} style={{background:C.teal,color:C.white,border:"none",borderRadius:22,padding:"9px 18px",fontSize:13,fontWeight:700,cursor:"pointer",opacity:loading||!input.trim()?0.5:1}}>Invia →</button>
        </div>
      </div>
    </div>
  );
}

// ─── ANALYTICS TAB ───────────────────────────────────────
function AnalyticsTab({ publishedItems }) {
  const KPI = ({label,value,sub,accent}) => (
    <div style={{background:C.white,border:`1px solid ${C.border}`,borderLeft:`4px solid ${accent}`,borderRadius:10,padding:"12px 16px"}}>
      <div style={{fontSize:24,fontWeight:800,color:C.text}}>{value}</div>
      <div style={{fontSize:11,fontWeight:700,color:C.mid,marginTop:2}}>{label}</div>
      {sub && <div style={{fontSize:10,color:C.muted,marginTop:2}}>{sub}</div>}
    </div>
  );

  return (
    <div style={{height:"100%",overflowY:"auto",padding:22}}>
      <div style={{marginBottom:16}}>
        <div style={{fontSize:10,fontWeight:800,color:C.teal,letterSpacing:3,marginBottom:4}}>DESTINATION INTELLIGENCE</div>
        <div style={{fontSize:20,fontWeight:800,color:C.text}}>Dashboard Analytics</div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:18}}>
        <KPI label="Query totali" value="1.247" sub="↑ +18%" accent={C.primary}/>
        <KPI label="Risoluzione" value="87%" sub="Soddisfacenti" accent={C.mint}/>
        <KPI label="Pubblicati" value={`${publishedItems.length}`} sub="via pipeline CIH" accent={C.green}/>
        <KPI label="Gap alert" value="5" sub="Opportunità" accent={C.amber}/>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"3fr 2fr",gap:14,marginBottom:14}}>
        <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontWeight:700,color:C.text,marginBottom:10}}>Query giornaliere</div>
          <ResponsiveContainer width="100%" height={140}><LineChart data={DAILY}><CartesianGrid strokeDasharray="3 3" stroke={C.border}/><XAxis dataKey="g" tick={{fontSize:9,fill:C.muted}} interval={4}/><YAxis tick={{fontSize:9,fill:C.muted}} width={24}/><Tooltip contentStyle={{fontSize:11,borderRadius:6}}/><Line type="monotone" dataKey="q" stroke={C.teal} strokeWidth={2} dot={false} name="Query"/></LineChart></ResponsiveContainer>
        </div>
        <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontWeight:700,color:C.text,marginBottom:10}}>Lingue</div>
          <ResponsiveContainer width="100%" height={90}><PieChart><Pie data={LANGS} dataKey="v" nameKey="name" cx="40%" cy="50%" outerRadius={38} innerRadius={20}>{LANGS.map((l,i)=><Cell key={i} fill={l.col}/>)}</Pie><Tooltip formatter={v=>`${v}%`}/></PieChart></ResponsiveContainer>
          <div style={{display:"flex",flexWrap:"wrap",gap:"3px 8px",marginTop:4}}>{LANGS.map(l=><div key={l.name} style={{display:"flex",alignItems:"center",gap:4,fontSize:10}}><div style={{width:7,height:7,borderRadius:"50%",background:l.col}}/><span style={{color:C.mid}}>{l.name} {l.v}%</span></div>)}</div>
        </div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>
        <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontWeight:700,color:C.text,marginBottom:10}}>Topic richiesti</div>
          <ResponsiveContainer width="100%" height={170}><BarChart data={TOPICS} layout="vertical"><XAxis type="number" tick={{fontSize:9,fill:C.muted}}/><YAxis dataKey="name" type="category" tick={{fontSize:10,fill:C.mid}} width={100}/><Tooltip contentStyle={{fontSize:11,borderRadius:6}}/><Bar dataKey="v" fill={C.teal} radius={[0,4,4,0]} name="Query"/></BarChart></ResponsiveContainer>
        </div>
        <div style={{background:C.amberBg,border:`2px solid ${C.amber}`,borderRadius:10,padding:16}}>
          <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12}}>
            <span style={{fontSize:16}}>⚠️</span>
            <div><div style={{fontSize:12,fontWeight:800,color:C.amber}}>Content Gap Alert</div><div style={{fontSize:10,color:C.muted}}>Domande senza risposta</div></div>
          </div>
          {GAPS.map((g,i) => (
            <div key={i} style={{background:C.white,borderRadius:7,padding:"7px 10px",marginBottom:7,border:g.hot?`1px solid ${C.amber}`:`1px solid ${C.border}`,display:"flex",alignItems:"center",justifyContent:"space-between",gap:6}}>
              <div style={{fontSize:11,color:C.text,flex:1}}>{g.hot&&<span style={{color:C.amber,fontSize:9,fontWeight:800,marginRight:4}}>🔥</span>}{g.q}</div>
              <div style={{display:"flex",gap:4,flexShrink:0,alignItems:"center"}}><span style={{fontSize:12,fontWeight:800,color:C.mid}}>{g.n}</span><Badge col={g.hot?C.red:C.muted} sm>{g.t}</Badge></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── ROOT ────────────────────────────────────────────────
export default function App() {
  const [tab,       setTab]       = useState("pipeline");
  const [published, setPublished] = useState([]);
  const [auditLog,  setAuditLog]  = useState([]);

  const handlePublish = useCallback(item => setPublished(p => [item, ...p]), []);
  const handleAudit   = useCallback(entry => setAuditLog(p => [entry, ...p]), []);

  const blockedCount = auditLog.filter(e => e.result === "blocked").length;

  const TABS = [
    { id:"pipeline",  label:"🔄 Pipeline E2E" },
    { id:"channels",  label:"📡 Output canali" },
    { id:"chat",      label:"💬 Assistente" },
    { id:"analytics", label:"📊 Intelligence" },
    { id:"audit",     label:`📋 Audit${auditLog.length>0?` (${auditLog.length})`:""} `, alert:blockedCount>0 },
  ];

  return (
    <div style={{fontFamily:"'Segoe UI',system-ui,sans-serif",height:"100vh",display:"flex",flexDirection:"column",background:C.light}}>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}} * {box-sizing:border-box;}`}</style>

      <div style={{background:C.dark,height:50,flexShrink:0,padding:"0 18px",display:"flex",alignItems:"center",gap:10}}>
        <div style={{display:"flex",alignItems:"center",gap:7}}>
          <div style={{width:9,height:9,borderRadius:"50%",background:C.mint,boxShadow:`0 0 0 3px ${C.mint}33`}}/>
          <span style={{color:"white",fontWeight:800,fontSize:14}}>Content Intelligence Hub</span>
        </div>
        <span style={{background:C.teal,color:"white",borderRadius:4,padding:"2px 7px",fontSize:10,fontWeight:800,letterSpacing:1}}>ABRUZZO · PoC E2E</span>
        <span style={{background:C.coral,color:"white",borderRadius:4,padding:"2px 7px",fontSize:10,fontWeight:800}}>🛡️ GUARDRAIL</span>
        {published.length > 0 && <span style={{background:C.green,color:"white",borderRadius:4,padding:"2px 7px",fontSize:10,fontWeight:800}}>{published.length} LIVE</span>}

        <div style={{marginLeft:"auto",display:"flex",background:"rgba(255,255,255,0.06)",borderRadius:7,padding:3,gap:2}}>
          {TABS.map(({ id, label, alert }) => (
            <button key={id} onClick={() => setTab(id)} style={{padding:"4px 12px",borderRadius:5,border:"none",cursor:"pointer",fontSize:12,fontWeight:tab===id?700:400,background:tab===id?C.mint:"transparent",color:tab===id?C.dark:alert?"#fca5a5":"rgba(255,255,255,0.6)",transition:"all 0.15s"}}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div style={{flex:1,overflow:"hidden"}}>
        {tab === "pipeline"  && <PipelineTab onPublish={handlePublish} onAudit={handleAudit}/>}
        {tab === "channels"  && <ChannelsTab items={published}/>}
        {tab === "chat"      && <ChatTab publishedItems={published}/>}
        {tab === "analytics" && <AnalyticsTab publishedItems={published}/>}
        {tab === "audit"     && <AuditTab log={auditLog}/>}
      </div>
    </div>
  );
}
