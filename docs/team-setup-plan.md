# Team-Setup: Vom Einzel-VPS zum teamfähigen Stack

Sechs Phasen, die den Stack teamfähig machen — **ohne dass jemand Zugang zur privaten
VPS braucht**. Die Reihenfolge ist bindend, die Phasen bauen aufeinander auf.

Stand: 10. September 2026 · Gesamtaufwand ca. 3–4 Tage
Fortschritt wird in diesem Dokument gepflegt (Kästchen abhaken).

---

## Ausgangslage

Vier Befunde aus dem laufenden System, die den Plan begründen:

| Befund | Bedeutung |
|---|---|
| **Keine lokale `.env`, leere `backend/data/`** | Entwickeln geht heute nur per SSH auf die Produktionsmaschine |
| **93 Backups, alle auf derselben Platte** | 67 MB in `backend/data/`, keine Rotation, nichts außer Haus — teilt jeden Ausfall mit dem Original |
| **Genau ein Rechner kann deployen** | Ulfs Laptop; die Hostinger-Firewall blockt SSH von GitHub-Runnern |
| **11 fremde Container auf der VPS** | Buzz-Stack, Hermes-Agenten, Traefik, dazu private Ablagen in `/root` — SSH dort ist nicht teilbar |

Was bereits steht und hier nicht angefasst wird: 24 Test-Dateien mit Unit/Integration-Trennung,
CI auf jedem PR, eine ungewöhnlich vollständige `docs/`, `CLAUDE.md` für KI-Assistenten.

---

## Phase 1 — Lokales Dev-Setup · 1 Tag

**Warum:** Solange Schlüssel und Daten nur auf dem Server liegen, führt jeder Weg zum
SSH-Zugang. Diese Phase schneidet die Abhängigkeit durch und ist Voraussetzung für alles Weitere.

- [x] **1.1 `pytest` in den Standard-Install nehmen**
  `CONTRIBUTING.md` sagt `uv sync`, danach `uv run pytest` — das schlägt fehl, weil die
  Test-Abhängigkeiten optional sind:
  ```
  $ uv sync && uv run pytest backend/tests -m "not integration"
  error: Failed to spawn: `pytest`
  ```
  Fix: Test-Abhängigkeiten zusätzlich in `[dependency-groups] dev` — `uv sync` installiert
  Dev-Gruppen automatisch. Die CI-Zeile `uv sync --extra test --group test` bleibt gültig.

- [x] **1.2 `.env.example` auf den Stand der VPS bringen**
  Verglichen mit `/opt/fact_check/.env` fehlen: `ACCESS_CODES`, `REQUESTY_API_KEY`,
  `LOGFIRE_TOKEN`, `GEMINI_MODEL_FACT_CHECKER_FALLBACK`.
  `ACCESS_CODES` ist der kritische — das Backend ist **fail-closed**: Fehlt die Variable,
  lehnt es jeden kostenverursachenden Endpunkt ab, ohne erkennbaren Grund für jemanden,
  der das System nicht kennt.

- [x] **1.3 Dev-Schlüssel: Selbstbedienung statt Verteilung**
  Ursprünglich als Ulf-Aufgabe geplant — besser ist, dass **jeder seinen eigenen Key anlegt**.
  Google AI Studio, Tavily und AssemblyAI haben Self-Signup mit Gratiskontingent. Damit geht
  kein Schlüssel durch Ulfs Hände, beim Ausscheiden ist nichts zu widerrufen, und jeder trägt
  sein eigenes Kontingent. Reduziert sich auf eine Doku-Zeile in `CONTRIBUTING.md`.
  Wichtig dort auch: **die Unit-Tests brauchen gar keine Keys** — nur Integrationstests und
  die echte Pipeline. Ohne diesen Hinweis denkt jeder Neue, er müsse zuerst drei Konten anlegen.

- [x] **1.4 `scripts/pull-db.sh` anlegen**
  Holt einen Datenstand zum lokalen Arbeiten, damit das Frontend echte Fact-Checks zeigt
  statt einer leeren Seite. Erste Fassung über SSH — **nur für Ulf**. In Phase 2 wird das
  Skript auf R2 umgestellt und damit teamtauglich.
  Immer die `backup-`Datei ziehen, nie die Live-DB — die wird gerade beschrieben.

- [x] **1.5 Zwei veraltete Doku-Stellen korrigieren**
  - `CONTRIBUTING.md` → Installationsschritt an 1.1 anpassen, Klon-URL richtigstellen
    (steht als `your-username/fact_check` drin).
  - `docs/onboarding-new-machine.md §4` → beschreibt einen `~/.zshrc`-`git`-Wrapper, der
    nach jedem Push automatisch deployt. **Den gibt es nicht mehr.** Für einen Neuen eine
    Falle: Er verlässt sich darauf, dass gepusht gleich deployt ist.

- [ ] **1.6 Optional: `config.py` nach `backend/`**
  Backend-Code importiert heute `from config import ...` aus dem Repo-Root — aus `app.py`,
  zwei Routern und vier Tests. Der Preis steht als Stolperfalle im eigenen Benchmark-Skript:
  `PYTHONPATH=/opt/fact_check ist nötig`. Mechanisches Refactoring, ~20 Minuten, eigener
  Commit. Angenehm für Neue, nicht dringend.

- [x] **1.7 Nachtrag: Unit-Tests hermetisch machen** *(bei der Abnahme aufgefallen)*
  `backend/app.py:32` ruft beim Import `load_dotenv()` auf — dadurch zieht die Test-Suite
  die echte `.env` des Entwicklers in `os.environ`. `test_llm_base.py` prüfte, ob
  `build_model()` ein blankes `GoogleModel` liefert, was nur ohne `REQUESTY_API_KEY` gilt.
  Der Test war also grün auf einer Maschine **ohne** `.env` und wäre rot auf der VPS und bei
  jedem Kollegen mit echten Keys. Jetzt über eine Fixture festgenagelt, plus zwei neue Tests
  für den Cross-Provider-Fallback, der bislang gar nicht abgedeckt war.

> **Abnahme:** Eine zweite Person klont frisch und hat in unter 30 Minuten grüne Tests und
> ein Frontend mit echten Daten — ohne einmal nach SSH-Zugang zu fragen.
>
> **Ergebnis (10.09.2026):** Bestanden. Aus einem Baum ohne `.venv` und ohne Datenbank:
> `uv sync` → `cp .env.example .env` → **260 Tests grün**, `ruff` sauber; `pull-db.sh` holt
> 319 Fact-Checks und 29 Sessions. Offen bleiben 1.3 (Konten, nur Ulf) und 1.6 (optional).

---

## Phase 2 — Backup nach R2 · ½ Tag

**Warum:** Löst zwei Dinge auf einmal — Schutz vor Plattenausfall, und den Datenpfad fürs
Team, der ohne Serverzugang auskommt.

- [ ] **2.1 R2-Bucket anlegen, zwei getrennte Tokens** *(nur Ulf — Konten)*
  Cloudflare R2, weil Frontend und Tunnel ohnehin dort liegen; ausgehender Traffic ist
  kostenfrei. Die DB ist ~700 KB und bleibt im Gratiskontingent.
  Ein **Schreibtoken** für die VPS, ein **Lesetoken** fürs Team, beide auf diesen Bucket
  beschränkt. Das Lesetoken ist der Ersatz für SSH.

- [x] **2.2 Litestream als systemd-Dienst einrichten**
  Litestream **0.5.17** per `.deb` installiert, Konfiguration in `/etc/litestream.yml`
  (`chmod 600`), Dienst `enable --now`. Die mitgelieferte systemd-Unit reicht — keine eigene nötig.
  Zwei Voreinstellungen von 0.5 waren für ein Backup zu knapp und wurden angehoben:
  Snapshots wurden nur **24 h** aufbewahrt, feingranulare Historie nur **5 min**. Jetzt:
  Snapshot alle 6 h, **30 Tage** Aufbewahrung, 24 h sekundengenaue Historie. Kostet bei
  ~700 KB Datenbank ein paar MB.
  Achtung beim Eintragen der Schlüssel: In YAML braucht es ein **Leerzeichen nach dem
  Doppelpunkt** — `key:wert` ist kein Schlüssel-Wert-Paar, sondern eine Zeichenkette.

- [x] **2.3a Alten Cron abschalten**
  `crontab -r`; die alte Zeile liegt gesichert unter `/root/crontab.backup-2026-09-10`.

- [x] **2.3b Die Altdateien nach R2 archiviert**
  Sie waren **nicht** redundant zu R2: Litestream repliziert erst ab Einrichtung, die
  Tageskopien reichten bis Juni zurück. Statt sie zu löschen, einmalig per `rclone` unter
  dem Prefix `archive/` gesichert (96 Dateien, 66 MB) — Litestreams `factcheck/`-Prefix
  bleibt unberührt. Vor dem lokalen Löschen dreifach geprüft: `rclone check` (0 Abweichungen,
  94 Treffer), Rückholtest der ältesten Datei (`backup-2026-06-09.db`, `integrity_check` ok,
  241 Fact-Checks), erst dann `rm`. Verzeichnis von 68 MB auf 2,8 MB.
  Eigenheit fürs Protokoll: `rclone` meldet gegen R2 im ersten Anlauf `501 NotImplemented`
  (ein S3-Aufruf zum Setzen der Änderungszeit, den Cloudflare nicht implementiert) und ist im
  zweiten erfolgreich. Die Daten sind nicht betroffen — der Prüfsummen-Abgleich belegt das.

- [x] **2.4 Restore testen**
  Restore aus R2 auf dem VPS: **319 Fact-Checks / 29 Sessions**, identisch zur Live-DB,
  `PRAGMA integrity_check` → `ok`.

- [x] **2.5 `pull-db.sh` von SSH auf R2 umstellen**
  Nutzt `litestream restore` mit `LITESTREAM_ACCESS_KEY_ID` / `LITESTREAM_SECRET_ACCESS_KEY`
  aus den vier `R2_*`-Variablen der lokalen `.env`. Kein SSH mehr nötig.
  Nebeneffekt, der zählt: Jeder Datenabruf im Alltag ist derselbe Restore-Pfad wie im
  Ernstfall — der Weg bleibt dadurch dauerhaft erprobt, statt einmal getestet und vergessen.
  Restore läuft in eine temporäre Datei und wird erst nach `integrity_check` eingewechselt,
  damit ein Abbruch nie die vorhandene lokale DB zerstört.
  Optionales Argument: Zeitpunkt (`./scripts/pull-db.sh 2026-09-08T21:00:00Z`).

> **Abnahme:** Ein Restore aus R2 auf dem Laptop ergibt dieselbe Zeilenzahl wie die Live-DB,
> und `pull-db.sh` läuft auf einem Rechner ohne SSH-Schlüssel durch.
>
> **Ergebnis (10.09.2026):** Bestanden. `./scripts/pull-db.sh` holt 319 Fact-Checks und
> 29 Sessions ausschließlich über den R2-Lesetoken; die Zeitpunkt-Variante
> (`./scripts/pull-db.sh <ISO-Zeit>`) ebenso. Gegenprobe: Ein Schreibversuch mit dem
> Lesetoken scheitert mit `403 AccessDenied` — die Rechtetrennung ist nicht nur
> konfiguriert, sondern nachgewiesen.

### Offen aus Phase 2

- [ ] **Schreib-Token rotieren.** Beim Debuggen eines YAML-Fehlers wurde `/etc/litestream.yml`
      im Klartext ausgegeben; damit stehen die Zugangsdaten des Schreib-Tokens in einem
      Chat-Transkript. Ersetzen: Token in Cloudflare löschen, neues Account-Token mit
      denselben Rechten anlegen (Object Read & Write, nur dieser Bucket), in
      `/etc/litestream.yml` eintragen, `systemctl restart litestream`.
- [ ] **`docs/deployment.md` nachziehen** — beschreibt noch den abgeschalteten 4-Uhr-Cron.

---

## Phase 3 — Logfire fürs Team öffnen · 5 Min

**Warum:** Der billigste Punkt der Liste — die Arbeit ist bereits getan.

- [ ] **3.1 Mitglieder ins bestehende Projekt einladen** *(nur Ulf — Konten)*
  Logfire läuft schon live: `LOGFIRE_TOKEN` ist auf der VPS gesetzt,
  `backend/services/observability.py` instrumentiert PydanticAI, Projekt unter
  `logfire-eu.pydantic.dev/mertensu/fact-check`. Es fehlt nur der Team-Zugang.
  Damit sieht das Team Traces, Fehler und LLM-Aufrufe im Browser statt `journalctl`.

- [ ] **3.2 Eine Zeile in die Doku**
  Wo die Logs liegen, steht bislang nirgends. Ein Satz in `docs/deployment.md` genügt —
  sonst sucht jeder Neue zuerst nach SSH.

> **Abnahme:** Ein Teammitglied findet den Trace eines fehlgeschlagenen Fact-Checks, ohne
> den Server anzufassen.

---

## Phase 4 — Dockerfile · ½ Tag

**Warum:** Macht die Laufumgebung reproduzierbar statt handgepflegt — und ist Vorarbeit für
Phase 5 und 6. Der Nutzen entsteht unabhängig davon, wo am Ende gehostet wird.

- [ ] **4.1 Tote Abhängigkeiten entfernen**
  `torch` und `silero-vad` stehen in `pyproject.toml`, werden aber nirgends im Code
  importiert; die CI installiert zusätzlich `portaudio19-dev` ohne Verwendung. Zusammen
  ~790 MB im venv. Vor dem Image-Bau raus, sonst wandert der Ballast in jede Schicht.

- [ ] **4.2 Rezept schreiben und lokal prüfen**
  Python 3.12, `uv sync`, App starten — etwa 15 Zeilen. Ersetzt die handschriftliche
  Provisioning-Anleitung in `docs/deployment.md` durch etwas Versioniertes, das lokal, in
  der CI und in Produktion identisch läuft. Beendet „bei mir läuft's" als Fehlerklasse.

- [ ] **4.3 Image in der CI bauen und nach GHCR schieben**
  Ein zusätzlicher Job in `.github/workflows/ci.yml`, nur auf `main`. Getaggt mit dem
  Commit-SHA — Grundlage für Rollbacks.

> ⚠️ **Einschränkung bleibt bestehen:** `backend/state.py` hält Claim-Queue und
> Pipeline-Status im Prozessspeicher. Der Kommentar in der Unit-Datei —
> `Single process required (no --workers, no --reload)` — gilt im Container unverändert.
> Ein Container ist keine Lösung dafür, er transportiert die Einschränkung mit.

> **Abnahme:** Das Image läuft lokal mit einem R2-Datenstand und beantwortet `/api/health`.

---

## Phase 5 — Branch protection + Deploy aus der CI · 1 Tag

**Warum:** Nimmt den Deploy vom Laptop und macht ihn zu etwas, das jeder im Team durch einen
Merge auslöst — ohne Maschinenzugang.

- [ ] **5.1 `main` schützen**
  PR erforderlich, CI muss grün sein, kein direkter Push. Ohne das ist die vorhandene CI
  Dekoration — jeder kann an ihr vorbei auf `main` pushen. Zehn Minuten in den Repo-Einstellungen.

- [ ] **5.2 Deploy umdrehen: Pull statt Push**
  Die Firewall blockt SSH von GitHub-Runnern — deshalb steht heute im Workflow ausdrücklich
  `no deploy job here`. Statt dagegen anzukämpfen, wird die Richtung getauscht: Die CI baut
  und veröffentlicht das Image, die VPS holt es sich.
  ```sh
  # auf der VPS, per Cron oder Webhook
  docker compose pull && docker compose up -d
  ```
  Damit entfällt jeder eingehende Zugang von außen — und der Laptop als Flaschenhals.

- [ ] **5.3 Secrets sauber trennen**
  Drei Orte, drei Zuständigkeiten — heute ist alles vermischt:

  | Was | Wo | Zugriff |
  |---|---|---|
  | Produktivschlüssel, `ACCESS_CODES` | `/opt/fact_check/.env` | nur Ulf |
  | GHCR-Token, Build-Secrets | GitHub Actions Secrets | Repo-Admins |
  | Dev-Schlüssel, R2-Lesetoken | lokale `.env` | jeder, eigene |

  Bekannte Falle mitdokumentieren: `deploy.sh` fasst die `.env` auf dem Server **nicht** an.
  Ein neues Secret im Code, das dort fehlt, lässt den Dienst beim nächsten Start scheitern.

- [ ] **5.4 Rollback definieren und einmal üben**
  Auf das vorherige Image-Tag zurückgehen und neu starten. Der Weg gehört in
  `docs/deployment.md` — ein Rollback, den niemand geübt hat, existiert im Ernstfall nicht.

- [ ] **5.5 Staging-Instanz aufsetzen**
  Zweiter Container auf derselben VPS: eigener Port, eigene Datenbank, eigene Subdomain.
  Kostet nichts und beendet die Lage, in der jeder Test auf dem System stattfindet, das
  abends live geht.

> ⚠️ **Vorher entschärfen:** `deploy/deploy.sh` führt auf dem Server `git reset --hard
> origin/main` aus — alles, was dort abweicht, wird kommentarlos gelöscht. Solange jemand die
> VPS noch als Arbeitsplatz benutzt, ist das ein Datenverlust-Risiko. Mit dem Image-Deploy
> verschwindet der Befehl; bis dahin gehört ein Warnhinweis in die Doku.

> **Abnahme:** Ein Teammitglied merged einen PR, und die Änderung geht live — ohne Ulfs
> Laptop, ohne SSH-Schlüssel, mit dokumentiertem Rückweg.

---

## Phase 6 — Umzug entscheiden · 1 Tag, wenn ja

**Warum am Ende:** Nach Phase 1–5 ist der Umzug ein Nachmittag statt eines Projekts — und die
Entscheidung fällt aus Ruhe statt aus Druck.

- [ ] **6.1 Der richtige Grund ist Zugriffstrennung, nicht Last**
  Das Backend läuft stabil; Leistung ist kein Argument. Das Argument ist: Ein gemeinsames
  Projekt sollte nicht auf einer privaten Maschine liegen, auf der ein fremder Agenten-Stack
  und persönliche Ablagen wohnen. Eine Plattform gibt dem Projekt eine eigene Organisation
  mit Rollen — `fly ssh console` führt in den Container dieser App, nicht auf die Maschine.

- [ ] **6.2 Fly.io — was konkret zu tun ist**
  `fly.toml` (Port, RAM, Volume, Region Frankfurt), Secrets per `fly secrets set`, DNS umziehen.
  Das Dockerfile aus Phase 4 wird unverändert übernommen.
  Zwei Nebeneffekte: Der `cloudflared`-Tunnel wird überflüssig — ein bewegliches Teil weniger.
  Und das Secret-Drift-Problem aus `onboarding-new-machine.md §4` verschwindet, weil es einen
  Ort für Secrets gibt statt zwei.
  **Kritische Einstellung:** `auto_stop_machines = false` und `min_machines_running = 1`.
  Sonst schläft die Maschine bei Leerlauf ein und nimmt die Claim-Queue mit.
  Litestream läuft weiter — ein Volume kann ebenso ausfallen wie eine Platte.

- [ ] **6.3 Die Alternativen ehrlich prüfen**
  - **Eigene VPS nur fürs Projekt** (Hetzner, ~5 €/Monat): löst die Zugriffstrennung sofort
    und vollständig, kleinster Schritt — aber die Hausmeisterrolle bleibt, jetzt für zwei Maschinen.
  - **Railway / Render**: wie Fly, bequemer, etwas teurer.
  - **Cloud Run, Lambda**: nein. Scale-to-zero ist mit dem In-Memory-State unvereinbar.

> **Entscheidungskriterium:** Erst angehen, wenn Phase 1–5 stehen. Wer alles gleichzeitig
> ändert, weiß bei Problemen nicht, woran es lag.

---

## Was nur Ulf erledigen kann

Drei Dinge hängen an Konten und lassen sich nicht delegieren — sie blockieren jeweils eine
ganze Phase:

- [ ] **R2-Konto und Bucket anlegen**, dann Schreib- und Lesetoken erzeugen → blockiert Phase 2
      und damit auch den Datenpfad fürs Team.
- [ ] **Dev-Schlüssel bei drei Anbietern** anlegen und Ausgabenlimits setzen → blockiert Phase 1.3.
- [ ] **Entscheiden, ob der Dienst weiter als `root` läuft.** Unabhängig vom Hosting sinnvoll:
      ein eigener `factcheck`-Nutzer mit Zugriff nur auf `/opt/fact_check`. Das ist der
      Unterschied zwischen „darf das Projekt neu starten" und „darf alles".
