"""Genera lo snapshot di Destination Intelligence dell'Abruzzo per ICH (Serbatoio 3).

Legge i dati REALI già raccolti e messi in cache dal progetto TDH (ISTAT presenze,
ISTAT capacità ricettiva, Banca d'Italia spesa turisti stranieri) e ne estrae un
sottoinsieme compatto, che viene versionato in data/intelligence/abruzzo_destination.json
così l'app gira in cloud senza dipendere dalla cache locale del TDH.

Uso (in locale, dopo un aggiornamento dati nel TDH):
    python tools/build_intelligence_snapshot.py [--tdh "PERCORSO/TDH_Engine/.cache"]
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_TDH = (Path(__file__).resolve().parent.parent.parent
               / "Motore Tourism Data HUB" / "TDH_Engine" / ".cache")
OUT = Path(__file__).resolve().parent.parent / "data" / "intelligence" / "abruzzo_destination.json"

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def build(tdh_cache: Path) -> dict:
    # ── Presenze ISTAT mensili (ITF1 = Abruzzo, tutte le provenienze) ──
    presenze_per_anno = defaultdict(dict)  # anno -> {mese:int -> presenze}
    with open(tdh_cache / "istat_ITF1_NI_ALL_WORLD.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            y, m, _ = row["date"].split("-")
            presenze_per_anno[int(y)][int(m)] = int(float(row["presences"]))

    anni = sorted(presenze_per_anno)
    annua = {y: sum(presenze_per_anno[y].values()) for y in anni}
    ultimo = anni[-1]
    mensili_ultimo = [
        {"mese": MESI[m - 1], "presenze": presenze_per_anno[ultimo].get(m, 0)}
        for m in range(1, 13)
    ]

    # ── Capacità ricettiva (posti letto per anno) ──
    letti = {}
    with open(tdh_cache / "istat_capacity_letti_ITF1.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            letti[int(row["anno"])] = int(float(row["letti"]))

    # ── Spesa turisti stranieri (Banca d'Italia) ──
    bdi = json.loads((tdh_cache / "bdi_extended.json").read_text(encoding="utf-8"))
    ab = bdi.get("abruzzo", {})
    spesa = {a: s for a, s in zip(ab.get("anni", []), ab.get("spesa", []))}

    # ── Connettività aerea (pax verso Pescara, indicatore di mercati esteri) ──
    conn = {}
    cpath = tdh_cache / "conn_ITF1.csv"
    if cpath.exists():
        with open(cpath, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conn[row["code"]] = int(row["pax"])

    return {
        "meta": {
            "descrizione": "Destination Intelligence Abruzzo — dati reali ISTAT/Banca d'Italia, estratti dalla cache del progetto TDH.",
            "fonte": "ISTAT (movimento e capacità esercizi ricettivi), Banca d'Italia (Indagine turismo internazionale)",
            "regione_istat": "ITF1",
            "anno_riferimento": ultimo,
        },
        "presenze_annue": annua,
        "presenze_mensili_ultimo_anno": mensili_ultimo,
        "posti_letto": letti,
        "spesa_stranieri_milioni": spesa,
        "connettivita_aerea_pax": conn,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdh", default=str(DEFAULT_TDH), help="Percorso della cartella .cache del TDH")
    args = ap.parse_args()
    tdh_cache = Path(args.tdh)
    if not tdh_cache.exists():
        raise SystemExit(f"Cache TDH non trovata: {tdh_cache}")
    snap = build(tdh_cache)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    a = snap["presenze_annue"]
    yr = snap["meta"]["anno_riferimento"]
    print(f"OK → {OUT}")
    print(f"   presenze {yr}: {a[str(yr)] if str(yr) in a else a[yr]:,} · "
          f"posti letto {yr}: {snap['posti_letto'].get(yr):,}")


if __name__ == "__main__":
    main()
