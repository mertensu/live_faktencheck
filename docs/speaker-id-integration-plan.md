# Speaker-Identifikation — Integrationsplan (Live Fast Lane)

Status: geplant, noch nicht implementiert. Dieses Dokument ist so geschrieben, dass die
Implementierung in einem frischen Kontext starten kann. Vorarbeit: Offline-Spike abgeschlossen
(`benchmarks/speaker_id_bench.py`), Ergebnis positiv — siehe Abschnitt „Spike-Belege".

## 1. Warum

Die Sprecherzuweisung im Live-Fast-Lane (`backend/services/streaming.py`) stützt sich auf
AssemblyAIs Streaming-**Diarisierung** (Labels A/B/…) plus eine LLM-Auflösung Label→Name. Das
ist auf Ein-Mikro-TV-Audio nicht robust:

- AssemblyAI v3 diarisiert per **Online-Reclustering**: Labels sind vorläufig und werden erst
  **nachträglich** per `SpeakerRevisionEvent` korrigiert (verzögert).
- Ein echter Lauf hatte alle Turns als Label „A" → alle Claims demselben Sprecher zugeordnet.
- Selbst mit korrektem Reclustering (`max_speakers` gesetzt, `SpeakerRevision` verarbeitet, LLM-
  Auflösung) bleibt die Kette fragil und zeitkritisch.

## 2. Kernentscheidung

**Die Sprecher-Identität wird unabhängig von AssemblyAIs Diarisierung bestimmt.**

- AssemblyAI liefert weiterhin **ASR**: Wörter, Wort-Zeitstempel, Text, Turn-/Satzgrenzen. Das
  ist zuverlässig und bleibt die Quelle für Transkript + Claims.
- Die **Identität** leiten wir selbst per **Voiceprint** ab: kontinuierlicher PCM-Ringpuffer, ein
  Hintergrund-Sliding-Window klassifiziert laufend gegen die **enrollten Gäste der Episode**
  (Closed-Set-Argmax, sherpa-onnx CAM++/ECAPA) → **eigener Sprecher-über-Zeit-Track**. Pro Claim
  lesen wir den dominanten Sprecher über die (per Wort-Zeitstempel bekannte) Zeitspanne des Satzes
  aus diesem Track. **Nicht** an AssemblyAI-Turns/Labels gebunden.
- AssemblyAIs `speaker_label` / `SpeakerRevisionEvent` werden zu **Fallback** degradiert: nur
  benutzt, wenn der Voiceprint unsicher ist (unbekannter Sprecher, zu kurz/leise, Überlappung).

Damit ist die Identität robust gegen falsche Diarisierungs-Labels *und* falsches Turn-Clustering:
selbst wenn AssemblyAI alles „A" nennt oder zwei Sprecher in einen Turn klebt, klassifizieren wir
das Satz-Audio direkt. Verbleibender harter Fall: echte Überlappung im selben Satz → gemischtes
Embedding → niedrige Confidence → Fallback (kein selbstbewusster Falsch-Name).

## 3. Datenfluss (Ziel)

Wichtig: Ein AssemblyAI-**„Turn" ist eine VAD-/Stille-basierte Äußerungsgrenze**, kein sauberes
Sprecher-Segment — eine Unterbrechung ohne Pause packt zwei Sprecher in *einen* Turn, und das
`speaker_label` daran ist die unzuverlässige, verzögerte Diarisierung. Wir hängen die Identität
deshalb **nicht** an Turns, sondern bauen einen **eigenen Sprecher-über-Zeit-Track**.

```
Browser PCM16 16k ──▶ StreamingSession.feed()
                        ├─▶ AssemblyAI (ASR: Wörter+Zeitstempel+Text)   [nur ASR nötig]
                        └─▶ kontinuierlicher PCM-Ringpuffer (~10–15 s)   [NEU]

Hintergrund-Task ──▶ Sliding-Window über den Puffer (z. B. 3-s-Fenster, 1-s-Hop)
   pro Fenster: Embedding → Argmax gegen enrollte Gäste → (name|unknown, score)
   └─▶ kompakter SPRECHER-TRACK: ein Eintrag pro ~Sekunde (name|unknown), Session-lang
       (winzig). Audio wird nach Klassifikation verworfen — nur der Track bleibt.

_flush_window() ──▶ Gate liefert Claims mit .source (Original-Satz)
   pro Claim: Satz → Wort-Zeitspanne [start_ms,end_ms]  (aus reliab. ASR-Zeitstempeln)
              └─▶ dominanten Sprecher über die Spanne aus dem TRACK lesen (Mehrheit)
                    eindeutig+confident → Claim-Sprecher; gemischt/unknown → Fallback
                    landet evtl. nach dem Claim → Rewrite-Plumbing (s. u.)
```

## 4. Granularität & Unabhängigkeit von AssemblyAI-Turns

- **Empfohlene v1: eigener Sprecher-Track per Sliding-Window** (oben). Vollständig unabhängig von
  AssemblyAIs Turn-/Label-Konzept; von AssemblyAI nur **Wort-Zeitstempel** (zuverlässige ASR), um
  zu wissen *wann* ein Satz gesprochen wurde. Erkennt Sprecherwechsel mitten im Turn, statt ihn
  wegzumitteln. Kosten: ~1 Embedding/Sekunde, ~zig ms CPU, im Hintergrund → über 90 min
  vernachlässigbar.
- **Einfachere Fallback-Variante: pro Claim-`source`-Satz slicen** (Satz → Wort-Span → PCM-Slice →
  `identify`). Weniger Embeddings, aber pro Satz *ein* gepooltes Embedding → sieht einen
  Sprecherwechsel innerhalb der Spanne nicht. Als Zwischenschritt ok; hinter derselben Schnittstelle
  austauschbar.
- **Unknown/Überlappung**: fällt in beiden Varianten unter das Cosinus-Gate → Fallback (kein
  selbstbewusster Falsch-Name).

### 4.1 Satz → Wort-Zeitspanne
Beide Varianten brauchen die **Zeitspanne** eines Satzes, nicht seine Turn-Zugehörigkeit. `source`
ist ein Satz-String aus dem **formatierten** Text; Zeitstempel hängen an den **Wörtern**
(`words[].start/end`, rohe ASR-Tokens) — passt nicht 1:1 (Groß/Klein, Satzzeichen, Zahlen). Mapping
= die Wort-Teilfolge finden, deren normalisierte Konkatenation dem Satz entspricht →
`start = words[i].start`, `end = words[j].end`. Fallback-Kette:
1. Normalisieren (lowercase, Satzzeichen weg, Whitespace glätten) → Satz als Teilstring der
   normalisierten Wortfolge → erstes/letztes Wort.
2. Sonst **Anker-Match** über die ersten/letzten Tokens.
3. Sonst grobe Zeit-Näherung (Fenster um die geschätzte Position) → Track abfragen.
4. Sonst ID skippen → Label behalten.
Im Track-Ansatz ist das unkritisch: wir brauchen nur eine ungefähre Spanne, um den dominanten
Sprecher abzulesen — nicht sample-genaue Satzgrenzen.

## 5. Neue Komponenten

### 5.1 `backend/services/speaker_id.py` (neu)
`SpeakerIdentifier`, lazy-loaded wie die anderen AI-Services (`services/registry.py`):
- `__init__(model_path, voiceprints: dict[str, np.ndarray], threshold, min_seconds)`
- `identify(pcm_float32: np.ndarray, sr=16000) -> tuple[str|None, float]`:
  Embedding berechnen (sherpa-onnx `SpeakerEmbeddingExtractor`), L2-normalisieren, Cosinus gegen
  alle Voiceprints, **Argmax**. Gibt `(name, top1)` zurück, wenn `top1 >= threshold` und
  Audiodauer `>= min_seconds`, sonst `(None, top1)`.
- ONNX-Extractor einmal bauen (num_threads aus Env), `provider="cpu"`.
- **Kein `soundfile` im Prod-Pfad**: das Live-Audio ist bereits PCM (PCM16→float32 per numpy);
  `soundfile` bleibt bench-only (WAV-Lesen).

### 5.2 Kontinuierlicher PCM-Ringpuffer + Sprecher-Track in `StreamingSession`
- In `feed(audio)`: PCM16-Bytes → float32, an einen **bounded, kontinuierlichen** Puffer anhängen;
  laufenden Sample-Offset mitführen. Puffer nur **~10–15 s** (genug für Sliding-Window + Slack) —
  Audio wird nach Klassifikation verworfen, **nicht pro Turn gespeichert**.
- Zeitachse: Wort-Zeitstempel (ms ab Session-Start) ↔ Sample-Index = `ms/1000*16000`. Wir
  kontrollieren die Sample-Zählung selbst.
- **Hintergrund-Klassifikator** (eigener Task): alle ~1 s das letzte 3-s-Fenster embedden →
  `identify` → Eintrag in den **Sprecher-Track** `self._spk_track: list[(t_sec, name|None, score)]`
  (winzig, Session-lang, Audio danach freigeben).
- `dominant_speaker(start_ms, end_ms) -> str|None`: Mehrheits-/gewichteter Vote der Track-Einträge
  in der Spanne; uneindeutig/leer → `None`.
- Fallback-Variante ohne Track: `_slice(start_ms,end_ms)` + einmal `identify` pro Claim-Satz.

### 5.3 Voiceprint-Store + Enrollment (offline)
- Store: `backend/data/voiceprints/<Name>.npy` (Unit-Vektor) **oder** eine kleine JSON/SQLite
  `{name: [floats]}`. Beim Sessionstart geladen, **gefiltert auf `episode.guests`** (+ optional
  Moderator). Closed-Set = die Gäste dieser Episode → wenige Verwechslungen, Nicht-Gäste fallen
  korrekt durchs Gate.
- Enrollment: **offline**, per erweitertem Bench (`benchmarks/enroll_voiceprints.py`, neu):
  liest `enroll/<Name>/*.wav`, mittelt Embeddings, schreibt den Store. Kein Enrollment im
  Live-Pfad.
- Pre-Show-Enrollment (kurzer Live-Clip pro Gast) ist ein späterer Zusatz; v1 = Store aus
  öffentlichen Clips.

## 6. Änderungen in `streaming.py` (konkrete Touchpoints)

1. `start()`: nichts an der ASR-Config nötig (Wörter+Zeitstempel liegen in `TurnEvent.words`,
   `Word.start/end`). `speaker_labels`/`max_speakers` können bleiben (Fallback-Pfad).
2. `_on_turn` → `handle_turn(...)`: `words` (Liste mit Zeitstempeln) mit durchreichen; an den
   Fenster-Puffer-Einträgen mitführen (für die Satz→Zeitspanne).
3. `feed`: kontinuierlichen PCM-Ringpuffer füttern; Hintergrund-Klassifikator baut den
   Sprecher-Track (5.2).
4. `_flush_window`: pro Claim `source`-Satz → Wort-Zeitspanne `[start_ms,end_ms]` (4.1) →
   `dominant_speaker(span)` aus dem Track lesen. Claim sofort mit best-bekanntem Sprecher
   speichern (Label/LLM), Track-Ergebnis kommt ggf. gleich/kurz danach → via Rewrite setzen.
6. **Rewrite-Plumbing wiederverwenden** (existiert bereits): `_turn_claims`/`_label_claims`,
   `_rewrite_speaker(pid, name)`, Event `claim_speaker_update` (Frontend `useAudioStream.js`
   behandelt es schon). Die Voiceprint-ID hängt sich in denselben nachträglichen Umschreibe-Pfad.
7. **Fallback-Kette pro Claim-Sprecher**: Voiceprint (falls confident) → LLM-Auflösung
   `speaker_map[label]` → rohes Diarisierungs-Label.

## 7. Gate / Schwellwerte (aus dem Spike, kalibrierbar)

- **Primär-Gate: absoluter Cosinus `top1 >= ~0.55–0.60`.** Im Spike trennte das unbekannte
  Sprecher sauber (0 % Unknown akzeptiert) von enrollten (Known-top1 ≥ 0.68).
- Argmax-Klassifikation war auch bei 3 ähnlichen Stimmen und 2-s-Segmenten 100 % korrekt.
- **Top1–Top2-Marge** als sekundäres Confidence-Signal (optional): große Marge = eindeutig. Im
  Spike war der absolute Cosinus der zuverlässigere Unknown-Filter; Marge nur ergänzend.
- `min_seconds` (~1.5 s): kürzere/leisere Sätze überspringen → Fallback.
- **Schwellwert auf echten Daten nachkalibrieren**: die Verteilung pro Satz (gepoolt) weicht von
  den Bench-Fixfenstern ab.

## 8. Konfiguration (Env, Feature-Flag)

- `SPEAKER_ID_ENABLED` (default `false`) — schaltet den ganzen Pfad; merkt sich dark deploybar.
- `SPEAKER_ID_MODEL` — Pfad zur .onnx (ins Image gebacken, s. u.).
- `SPEAKER_ID_THRESHOLD` (default ~0.55).
- `SPEAKER_ID_MIN_SECONDS` (default 1.5).
- `SPEAKER_ID_NUM_THREADS` (default 1).
- `SPEAKER_ID_VOICEPRINTS_DIR` (default `backend/data/voiceprints`).
- Import von sherpa-onnx **lazy** in `speaker_id.py`, damit ein deaktiviertes Flag den ONNX-Stack
  gar nicht erst lädt.

## 9. Deployment-Entscheidung

**Empfehlung: In-Process** (Embedding im Backend-Container), nicht Sidecar.
- Last ist klein: ein Embedding pro Claim-Satz, ~zig ms CPU, off hot path. Kein IPC/Extra-Ops.
- Prod-Dependencies: `sherpa-onnx`, `onnxruntime`, `numpy` aus der `bench`-Gruppe in die
  **Haupt-Dependencies** (oder ein `speakerid`-Extra, das der Dockerfile installiert). `soundfile`
  bleibt bench-only. Image wächst ~200 MB (onnxruntime); akzeptabel.
- **Modell-Datei** (~27 MB) ins Image `COPY`-en (reproduzierbar) statt zur Laufzeit ziehen.
- macOS-Dev-Hinweis (nur lokal): sherpa-onnx-Wheel findet `libonnxruntime.dylib` nicht — Symlink
  nötig (im `speaker_id_bench.py`-Header dokumentiert). Auf Linux/CI/VPS kein Thema.
- Sidecar nur erwägen, falls CPU-Kontention mit den Fact-Checkern real wird.

## 10. Tests

- Unit: `SpeakerIdentifier` per Stub in `StreamingSession` injizieren (wie `gate`/`fast_checker`):
  `identify(pcm)->(name,score)`. Fälle: confident → Label überschrieben; unknown/None → Label
  bleibt; async ID landet nach dem Claim → `claim_speaker_update` + DB-`sprecher` umgeschrieben.
  **Kein onnxruntime in Unit-Tests** (Stub).
- Satz→Wort-Span-Mapping separat testen (Textausrichtung auf `words`).
- Genauigkeit bleibt im **Offline-Bench** (`benchmarks/`, echtes Audio), nicht in Unit-Tests.

## 11. Rollout

1. Hinter `SPEAKER_ID_ENABLED=false` mergen (dark).
2. Wiederkehrende Gäste enrollen (Store bauen), Modell ins Image.
3. Auf **Staging** aktivieren (Branch-Auto-Deploy ist scharf), echte Session mitschneiden,
   Voiceprint-IDs gegen die Realität prüfen, Threshold nachkalibrieren.
4. Erst dann Prod aktivieren.

## 12. Offene Risiken

- **Echte Überlappung/Crosstalk** im selben Satz → gemischtes Embedding → niedrige Confidence →
  Fallback. Sichere Degradation, aber im Live-Betrieb beobachten (offline mit sauberen Clips nicht
  messbar).
- **Threshold-Kalibrierung** auf gepoolten Satz-Embeddings vs. Bench-Fixfenster.
- **Enrollment-Domänenlücke** (öffentliche Clips vs. Studio) — im Spike als Cross-Recording schon
  teilvalidiert (Marge schrumpft mit ähnlichen Stimmen), auf echten Daten weiter beobachten.
- **Puffer-Speicher**: Audio-Ringpuffer nur ~10–15 s (nach Klassifikation freigeben); der
  Sprecher-Track selbst ist winzig (ein Eintrag/Sekunde) und darf Session-lang bleiben.
- **Satz→Span-Alignment**: robuste Textausrichtung nötig (Reformulierer ändert den Claim-Text,
  aber `source` ist der Originalsatz → gegen `words` matchbar).

## 13. Spike-Belege (Kontext für die Umsetzung)

- Modell: `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` (CAM++, dim=192), aus dem
  k2-fsa-Release-Tag `speaker-recongition-models` (Tippfehler im Tag ist echt).
- Bench: `benchmarks/speaker_id_bench.py`, Daten (git-ignoriert) unter
  `benchmarks/data/speaker_id/{enroll,eval}/<Name>/*.wav` (16k mono).
- Ergebnisse (Connemann/Dröge/Maischberger, je 1 Enroll-Clip, versch. YouTube-Aufnahmen):
  - 3 Sprecher: Argmax-Accuracy **100 %**; Impostor-Cosinus steigt mit ähnlichen (weibl.) Stimmen
    (max 0.55), Marge schrumpft auf ~0.13, bleibt aber getrennt.
  - Kurzsegment 2/3/5 s: Accuracy **100 %**, Top1–Top2-Marge stabil ≥ 0.13.
  - Unknown-Rejection (Eindringling nicht enrollt): Gate `cos>=0.55` → **0 % Unknown**, 83 % Known
    akzeptiert (Rest fällt auf Label zurück).
- Bewertung: grünes Licht; harter ungetesteter Rest = echter Crosstalk.
