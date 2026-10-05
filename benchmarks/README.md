# Pipeline-Benchmarks

Wiederholbare A/B-Tests für Timing, Qualität und Kosten der Live-Lane.
Gedacht als Ausgangspunkt, wenn ein Modellwechsel oder eine Konfig-Änderung
bewertet werden soll. Die Skripte machen echte, kostenpflichtige API-Calls und
teilen sich das Tavily-Budget mit Produktion und Staging.

| Skript | Misst |
|---|---|
| `fast_check_ab.py` | Schneller Checker: alter vs. neuer Aufbau (Suchanfragen, Tavily-Tiefe, Snippet-Länge, Prompt) auf echten Claims |
| `jev_gate_bench.py` | Jev als Satz-Gate: Wahrscheinlichkeit pro Satz, Latenz, Schwellen-Band |
| `grey_zone_bench.py` | Grauzone: Jev-Band + LLM-Zweitmeinung auf Atalay-Sätzen (sollen durch) und Meinungen (sollen raus); `python -m benchmarks.grey_zone_bench` |

Aufruf und Env-Stellschrauben stehen jeweils im Docstring des Skripts. Als Input
eignen sich echte Claims aus einem DB-Snapshot (`./scripts/pull-db.sh`).

Der Benchmark für die alte Block-Pipeline (`model_ab.py`: Sprecher-Auflösung,
Extraktion, tiefer Checker) ist mit dieser entfernt worden; Stand bei Tag `v0.1.0`.

## Stolperfallen (aus Erfahrung)

- `PYTHONPATH` auf das Projekt-Root setzen: Bei einem Skript liegt dessen eigenes
  Verzeichnis auf `sys.path`, nicht das Projekt-Root — ohne die Variable schlägt schon
  `import backend` fehl.
- Ergebnis-Dicts nutzen **englische** Keys: `consistency`, `sources`, `evidence`
  (der deutsche `quellen` entsteht erst beim DB-Mapping in `utils.py`).
- **Hohe Streuung:** Such- und Modell-Latenz schwanken je nach API-Last deutlich.
  Für belastbare Aussagen 2–3 Läufe mitteln.
- Diese Benchmarks ändern bewusst nichts an der laufenden App.
