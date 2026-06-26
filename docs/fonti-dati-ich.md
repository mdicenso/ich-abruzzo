# ICH — Fonti dati per passare da PoC a sistema reale

> Documento di lavoro. Nasce dalla lettura del bando originario
> (`Bando_AVVISO_manifestazione_INTERESSE_IA_2.pdf` — GAL Valle Umbra e Sibillini,
> Umbria), che è la *specifica funzionale* dell'idea poi adattata all'Abruzzo.

## Cosa impone/conferma il bando

Un **Assistente Virtuale Turistico** sui siti istituzionali, alimentato da una
*base conoscitiva* di contenuti di qualità forniti da enti pubblici/no-profit.
Vincoli che mappano 1:1 su ICH:

- contenuti **territoriali e collettivi**, **mai imprese o marchi commerciali**
  → Guardrail "no promozione commerciale";
- trattamento dati GDPR → check GDPR;
- fonti ammesse: link a siti istituzionali, .doc/.docx, **.pdf nativo (non scansioni)**;
- contenuti "previa verifica e assunzione di responsabilità" → la pipeline + guardrail;
- tassonomia tematica esplicita (natura, agroalimentare, borghi, cammini, identità…).

## I 3 serbatoi di dati (NON sono un blob unico)

### 1. Knowledge Base territoriale (cuore dell'assistente) — statico, curato
Aggiornamento raro (annuale/stagionale). Va **versionato nel repo** (disco cloud effimero).

| Tema | Fonte | Formato/accesso |
|---|---|---|
| Patrimonio culturale | MiC Luoghi della Cultura/DBUnico; ICCD Catalogo Beni Culturali | open data JSON/CSV, API |
| Borghi e identità | Borghi più Belli d'Italia; Bandiere Arancioni (TCI); Wikipedia/Wikidata | liste + SPARQL Wikidata |
| Enogastronomia | eAmbrosia/Qualigeo (DOP-IGP); PAT MASAF (Abruzzo); Slow Food presìdi; Strade del Vino | CSV/PDF ufficiali |
| Natura/sentieri | Parchi (Majella 1.200km GPS, Gran Sasso-Laga, PNALM); EUAP aree protette; AMP Torre del Cerrano; OpenStreetMap (Overpass) | GPX, GeoJSON, API |
| Cammini/turismo lento | Atlante dei Cammini d'Italia (MiC); Sentiero della Libertà; Cammino dei Briganti | schede ufficiali |
| Spiagge/costa | Bandiere Blu (FEE); Costa dei Trabocchi | liste annuali |

### 2. Flusso eventi & news (la pipeline) — dinamico
Sostituisce `SOURCE_ITEMS` hardcoded. Crawling periodico, preferire RSS/sitemap/open-data.

| Ente | Fonte | Lettura |
|---|---|---|
| APT regionale | abruzzoturismo.it (calendario eventi) — **fonte aggregata migliore** | RSS/scraping |
| Comuni | siti istituzionali, albo pretorio, sezioni eventi | RSS/sitemap.xml/scraping mirato |
| Parchi | Majella, Gran Sasso, PNALM (avvisi sentieri/eventi) | RSS/news |
| GAL | Gran Sasso Velino, Maiella Verde, Costa dei Trabocchi, Terre Pescaresi… | news/bandi |
| Pro Loco | UNPLI Abruzzo + Pro Loco locali (sagre) | scraping |
| IAT/Diocesi | uffici turistici; eventi religiosi (Perdonanza) | scraping mirato |

### 3. Intelligence / domanda turistica (dashboard) — riusare TDH!
TDH già gestisce ISTAT/BdI/Eurostat/Trends con cache. ICH attinge da lì, non rifà.

| Segnale | Fonte | Nota |
|---|---|---|
| Interesse/ricerche | Google Trends (pytrends, già in TDH) | i "content gap" diventano reali |
| Arrivi/presenze | ISTAT movimento turistico | ⚠️ vincolo: no presenze mensili per singolo paese estero a livello regionale |
| Capacità ricettiva | ISTAT posti letto | per provincia |
| Spesa stranieri | Banca d'Italia – Indagine turismo internazionale | per regione |
| Domanda reale | log delle query dell'assistente | in produzione è la fonte più preziosa |

## Vincoli concreti

1. **Proxy Indra**: crawling esterno via `truststore` (in locale c'è il proxy, in cloud no).
2. **Disco effimero Streamlit Cloud**: KB/cache versionati nel repo o storage esterno; niente crawling live ad ogni avvio.
3. **Legale/etico**: robots.txt; solo contenuti collettivi, no marchi commerciali (esclude Booking/TripAdvisor).
4. **Formati**: .pdf nativo → estrazione testo (es. `pypdf`).

## Primo passo proposto

- Valore percepito subito → **Serbatoio 2** (eventi reali da abruzzoturismo.it): pipeline da finta a vera.
- Fedeltà al bando / utilità assistente → **Serbatoio 1** (KB).
- Quasi gratis → **Serbatoio 3** riusando TDH.
