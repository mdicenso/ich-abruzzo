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

#### Esito della ricognizione feed (29-07-2026) — leggere prima di ricercare

Sweep sistematico con `tools/probe_sources.py` (identifica il CMS, cerca `href=…rss`
in tutto l'HTML e tenta i path noti WordPress/Drupal/Joomla). **Risultato: nessuna
fonte nuova utilizzabile.** Le 3 in produzione (ANSA Abruzzo, Regione Abruzzo,
Parco Majella) sono, allo stato, quasi tutto ciò che l'ecosistema abruzzese espone
via feed. Dettaglio dei vicoli ciechi, così non si ribattono:

| Candidato | Esito | Nota |
|---|---|---|
| abruzzoturismo.it | **nessun feed** | Drupal senza Views RSS: 404 su `/rss.xml`, `*.rss`, `/node/feed`. Raggiungibile (i 502 da PC Indra sono il proxy). Serve il connettore sitemap/HTML |
| Comuni (Sulmona, Scanno, Pescocostanzo, Civitella, Vasto, L'Aquila) | **nessun feed** | i CMS AgID del modello comunale non espongono più RSS |
| Parchi (Gran Sasso, PNALM, Sirente-Velino) | **nessun feed** | Gran Sasso risponde 502 anche da fuori rete Indra (sito giù) |
| GAL abruzzesi | **nessun feed utile** | 4 dei 5 domini non risolvono; Gran Sasso Velino ha `/rss` valido ma **vuoto, fermo al 2015** |
| UNPLI Abruzzo, CCIAA Chieti-Pescara, MiC | **nessun feed** | WordPress ma feed disattivato (UNPLI) |
| Borghi più belli d'Italia | feed vivo, **scartato** | nazionale e autoreferenziale; `/category/abruzzo/feed/` ha 1 solo item |
| sanita.regione.abruzzo.it | feed vivi (`<canale>.rss`) | pattern Drupal Views funzionante, ma tema **sanitario**: fuori perimetro editoriale |

**Conclusione operativa:** la strada dei feed è vicina alla saturazione. Per crescere
in copertura servono i connettori che *non* dipendono dal feed — **sitemap/HTML** (per
abruzzoturismo, il target di maggior valore) e **PDF** avvisi.

**Ipotesi caduta:** il CMS «Sitoper» non esiste come vendor — era una stringa
nell'HTML della Majella. Non c'è quindi nessun "pattern moltiplicatore" da sfruttare
sui siti dei comuni.

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
