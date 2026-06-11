# Roadmap — Von „Live Faktencheck" zur Multi-User-App

**Stand:** 2026-06-10
**Branch dieser Arbeit:** `worktree-session-multitenancy` (Phasen 1, 1b, 3a, R, Q abgeschlossen; nicht gemergt)

Dieses Dokument hält den Gesamtplan und die bereits getroffenen Entscheidungen fest,
damit die Arbeit später nahtlos fortgesetzt werden kann. Jede Phase bekommt einen
eigenen Spec → Plan → Implementierungs-Zyklus (Brainstorming-Workflow).

---

## Vision

Aus dem heutigen Single-Operator-System (lokales Backend, hartkodierte Episode, ein
Moderator) eine **gehostete App** machen, bei der **viele Nutzer parallel eigene
Live-Faktencheck-Sessions** fahren — Audio per Browser-Mikrofon, Selbst-Moderation,
Ergebnisse privat per Link teilbar.

## Festgelegte Rahmenentscheidungen (gelten phasenübergreifend)

- **Zielgruppe:** breite Öffentlichkeit (Journalisten waren nur ein Beispiel).
- **Audio-Quelle:** Browser-Mikrofon (Desktop + Handy). Tab-/System-Audio via
  Bildschirm-Sharing optional später (ersetzt das lokale BlackHole).
- **Moderation:** jeder Nutzer moderiert seine eigene Session selbst (Human-in-the-Loop).
- **Zugang:** vorerst per Zugangscode (kein offenes Registrierungssystem).
- **Sichtbarkeit:** neue Sessions sind privat, nur per Link abrufbar. Die bestehenden
  veröffentlichten Episoden bleiben als Legacy öffentlich.
- **Hosting:** vorhandener Hostinger-VPS (dauerhafter Prozess, gut für Live-Audio —
  bewusst KEIN Serverless wie wahl.chat, das ist nur für zustandslose Chatbots optimal).
- **Frontend bleibt** React+Vite auf Cloudflare Pages; Domain `live-faktencheck.de`
  bei Cloudflare. Kein Next.js-Wechsel (lohnt nicht).
- **DB bleibt SQLite** (Single-Writer + WAL reicht bei wenigen parallelen Sessions;
  Postgres erst bei vielen gleichzeitigen Schreibern neu bewerten). Persistenz ist mit
  Multi-Tenancy wichtiger, nicht unwichtiger.
- **Architektur:** Chunk-POST + Polling beibehalten (kein WebSocket-Rewrite).

---

## Phasenübersicht

| Phase | Inhalt | Status |
|-------|--------|--------|
| **1** | Backend-Multi-Tenancy (Sessions statt globaler Episode) | ✅ **Abgeschlossen** |
| **1b** | Homepage / App-Informationsarchitektur neu denken | ✅ **Abgeschlossen** |
| **2** | Browser-Audio-Capture (ersetzt `listener.py`) | ⬜ Offen |
| **3a** | **Minimaler Zugangs-Gate (Zugangscodes auf Kosten-Endpunkten)** | ✅ **Live auf VPS** (2026-06-10, `971a7de`; main-Merge offen) |
| **R** | **Agent-Rewrite: LangChain/LangGraph → PydanticAI + Logfire** | ✅ **Abgeschlossen** (2026-06-10, Branch; main-Merge = Go-Live offen) |
| **Q** | Quick Check (One-Shot-Zitat → Fact-Check, ohne Audio) | ✅ **Abgeschlossen** (2026-06-10, Branch; main-Merge = Go-Live offen) |
| **3b** | Live-Limits (10-Min-Session-Auto-Stop, ggf. Circuit Breaker) | ⬜ Offen |
| **4** | VPS-Deployment (kein lokaler Start, JSON-Export entfällt) | 🟡 Backend live auf VPS; Go-Live-Merge offen |

> **Reframing 2026-06-10:** Die alte „Phase 3 = Codes + Limits" wurde aufgeteilt. Auslöser:
> (1) das Backend ist seit dem VPS-Cutover **öffentlich + unauthentifiziert** erreichbar
> (CORS schützt NICHT vor `curl`/Bots) → der Zugangs-Gate ist *jetzt* dringend, nicht „vor
> dem Rollout"; (2) eine neue **Quick-Check**-Idee (Text-Zitat → Fact-Check) ist unabhängig
> von Phase 2 (Browser-Audio) und der billigste/schnellste Weg zu einem nutzbaren Produkt.
> Der aktuelle Arbeitsschritt ist bewusst **nur** der minimale Gate (Phase 3a); Quick Check
> und Live-Limits bekommen eigene Specs.

---

## ✅ Phase 1 — Session-Multi-Tenancy (ABGESCHLOSSEN)

**Spec:** `docs/superpowers/specs/2026-06-09-session-multitenancy-design.md`
**Plan:** `docs/superpowers/plans/2026-06-09-session-multitenancy.md`

**Was gebaut wurde:**
- Neue `sessions`-DB-Tabelle + CRUD; aus „Episode" wird eine zur Laufzeit erzeugte
  DB-Session. Spalte `episode_key` → `session_id` (idempotente Migration).
- Legacy-`EPISODES` werden beim Startup als öffentliche Sessions geseedet
  (`session_id == alter episode_key`, daher bleiben alte Fact-Checks 1:1 erhalten).
- `Episode.from_session_row` / `episode_to_session_dict` Mapping-Helfer.
- Sessions-Router: `POST /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/end`.
- Alle Router (audio, claims, fact_checks, config) + `pipeline.py`-Retrigger nach
  `session_id` gescoped. Globaler `current_episode_key` entfernt. `POST /set-episode`
  entfernt. `/api/health` liefert `active_sessions`.
- Queue-Worker-Concurrency (`asyncio.Semaphore`) unverändert; Items tragen `session_id`.
- Frontend: „Session anlegen"-Formular (`/new`), `session_id`-Scoping, teilbarer
  Link `/{session_id}`.
- `listener.py` sendet `session_id` (statt `episode_key`; `set-episode`-Aufruf entfernt).
- 181 Unit-Tests grün, inkl. Isolations-Regressionstest (zwei Sessions sehen sich nicht).

**Ergebnis:** Viele Sessions können parallel und isoliert laufen. Backend ist
multi-tenant-fähig.

---

## ✅ Phase 1b — Homepage / Informationsarchitektur (ABGESCHLOSSEN)

**Spec:** `docs/superpowers/specs/2026-06-10-homepage-ia-design.md`
**Plan:** `docs/superpowers/plans/2026-06-10-homepage-ia.md`
**Status:** Implementiert + verifiziert auf Branch `worktree-session-multitenancy`
(2026-06-10, Commits `43179da`→`1789e65`). **NICHT nach main gemergt** — Merge = Go-Live (Phase 4).

**Warum:** Sobald Sessions privat/per-Link sind, verliert die Startseite ihren
„Schaufenster"-Zweck. Statt zweier Varianten (Prod/Dev) gibt es jetzt **eine
ausgewogene Landing-Page** mit klarem Einstieg.

**Was gebaut wurde:**
- **Neue Homepage** (`HomePage.jsx`): Hero → **ein** Zugangscode-Unlock → **zwei
  gleichwertige Action-Cards** (Quick Check `/pruefen` + Live-Session `/new` mit
  „beta"-Tag) → **Beispiele**-Sektion (`#beispiele`, Legacy-Episoden als flache
  Liste, `test` herausgefiltert). Die alte `isProduction`-Verzweigung ist raus.
  Gesperrte Cards sind `aria-disabled`-Buttons, die den Unlock fokussieren.
- **`GET /api/validate-code`** (`config.py`): billiger, **seiteneffektfreier**
  Code-Check für den Homepage-Unlock; liefert nur `{name, quick_check_limit,
  quick_checks_used}` (nie das rohe Code-/`active`-Feld). 5 neue Gate-Tests.
- **`AccessUnlock`-Komponente** (`forwardRef`, `focus()` exponiert): validiert den
  Code, speichert ihn in `localStorage`, zeigt „Freigeschaltet"-Status; rendert
  sofort entsperrt, wenn schon ein Code gespeichert ist. Code wird app-weit via
  `localStorage` (`fc_access_code`) geteilt; Flow-Seiten behalten ihr eigenes
  Code-Feld als Deep-Link-Fallback.
- **Navigation:** „Beispiele"-Link (`/#beispiele`); `ScrollToHash` in `App.jsx`
  (BrowserRouter scrollt nicht nativ zu Hash-Ankern).
- **`/pruefen`-Politur:** Kontrast-Fix der Formularfelder (vorher dunkle Felder mit
  grauem Text → echte Light-Theme-Tokens), redundantes Zugangscode-Feld nur noch als
  Fallback, **Gemini-artige abgerundete Prompt-Box** (`.claim-box`, Auto-Grow,
  Enter=Senden / Shift+Enter=Zeilenumbruch, kreisrunder Senden-Button + Spinner).
- **Relicense** (`ce5bc02`, eigenständig): MIT → **PolyForm Noncommercial 1.0.0**
  (source-available, nur nicht-kommerziell; Required Notices für `live-faktencheck.de`
  + `Copyright 2026 Ulf Mertens`). README-Lizenzabschnitt angepasst.

**Verifikation:** 209 Unit-Tests grün, ruff clean, Frontend-Build ok. Umgesetzt via
subagent-driven-development (Spec- + Code-Quality-Review pro Task); finaler holistischer
Review = „ready to merge". Manueller Klick-Test deckte 3 UI-Punkte auf — 2 echte gefixt
(Kontrast, redundantes Code-Feld), der dritte („Beispiele zeigen keine Claims") war ein
Test-DB-Artefakt (In-Memory-DB seedet nur Session-Metadaten, keine Fact-Checks).

**Abhängigkeiten:** keine harten; baute auf Phase Q (`/pruefen`) + Phase 3a (Gate) auf.

---

## ⬜ Phase 2 — Browser-Audio-Capture

**Ziel:** `listener.py` durch Browser-Aufnahme ersetzen. Der Browser nimmt das
Mikrofon (Desktop/Handy) in festen Blöcken auf und POSTet sie an `/api/audio-block`
mit `session_id` — exakt das Contract, das `listener.py` heute schon nutzt.

**Technische Eckpunkte:**
- `MediaRecorder`-API im Browser; Aufnahme in N-Sekunden-Chunks, Upload als
  multipart an den bestehenden Audio-Block-Endpunkt. Kein WebSocket nötig.
- Backend-seitig ist nichts Großes nötig — der Endpunkt existiert und ist
  session-scoped. Ggf. Audioformat-Handling (WebM/Opus vom Browser vs. WAV) prüfen:
  AssemblyAI akzeptiert mehrere Formate; Transkriptions-Service ggf. anpassen.
- UI: „Aufnahme starten/stoppen" auf der Live-Seite der Session; Statusanzeige der
  Pipeline-Events (existiert: `/api/pipeline-status`).
- Optional/später: Tab-/System-Audio via `getDisplayMedia({audio:true})` für Shows,
  die im Web laufen (BlackHole-Ersatz).

### Frontend / Nutzerführung — Session-Setup-Wizard

**Problem:** Ein Live-Check braucht vorab Metadaten, die heute hartcodiert in
`config.py` stehen (`Episode`: `show`/`date`/`guests`/`context`). Im Self-Service muss
der Nutzer sie liefern — aber unterschiedlich je nach Gesprächssituation (politische
Talkshow mit benannten Gästen vs. privates Gespräch mit Verwandten). Statt eines
überladenen Formulars: ein **geführter Wizard**, eine Frage pro Schritt, verzweigt nach
Gesprächsart.

**Umsetzung:** Ein-Route-Wizard auf `/new` — interne Schritt-Zustandsmaschine +
Fortschrittsanzeige, animierte Übergänge, Zurück/Weiter über State. (Verworfen:
Route-pro-Schritt = unnötiges Plumbing; langes Formular = widerspricht „eine Frage nach
der anderen".)

**Wizard-Flow:**

1. **Gesprächsart** (drei Kacheln): 🏛️ Öffentliche Debatte / Talkshow · 🎙️ Interview ·
   💬 Privates Gespräch.
2. **Personen** (verzweigt nach Auswahl):
   - *Öffentliche Debatte:* dynamische Personen-Liste, pro Person **Name + Partei/
     Organisation + Rolle/Funktion** („weitere Person hinzufügen").
   - *Interview:* interviewte Person (Name + Partei/Org + Rolle) · interviewende Person/
     Medium (nur Name, optional).
   - *Privates Gespräch:* Teilnehmende nur als **Vorname/Rolle**, keine Partei — bewusst
     schlank; Personenliste optional.
3. **Thema (optional):** Freitext „Worum geht es?", überspringbar (v.a. beim privaten
   Gespräch). Wird übersprungen → `context` defaultet automatisch auf ein vom
   Gesprächstyp abgeleitetes Label („Öffentliche Debatte" / „Interview" / „Privates
   Gespräch"), damit das Modell immer minimalen Kontext hat.
4. **Übersicht & Start:** Zusammenfassung aller Angaben → „Aufnahme starten".
   Datum = automatisch heute.

**Backend-Anbindung:** Mapping auf den Session-Erstellungs-Payload (Phase 1): `type`,
strukturierte `participants[]` (name/party/role), `context` (optional → Typ-Default),
`date=heute`. Die Namen speisen Sprecher-Auflösung + Claim-Kontext (`guests`). Nötige
Backend-Änderung: Session-Payload um `type` und strukturierte `participants` erweitern
(heute nur flache `guests`-Liste).

**Abhängigkeiten:** Phase 1 (Session-Scoping) — erfüllt.

---

## ✅ Phase 3a — Minimaler Zugangs-Gate (LIVE auf VPS)

**Spec:** `docs/superpowers/specs/2026-06-10-access-gate-design.md`
**Status:** Implementiert + deployed (Commit `971a7de`, 2026-06-10). Gate live auf dem VPS
(`ACCESS_CODES=ulfkai:0311`, codes-Tabelle geseedet); verifiziert: ohne Code→401, falsch→403,
`0311`→201, GETs offen, `/api/health` ok. **Offen:** Provider-Budget-Caps (manuell) + optionales
Nachgaten von `POST /api/fact-checks`/`pending-claims`; Branch noch nicht nach main gemergt.

**Ziel:** Die seit dem VPS-Cutover offene, unauthentifizierte API schließen — mit der
kleinsten Änderung, die wirkt. Kein Feature-Ausbau.

**Technische Eckpunkte:**
- Neue `codes`-Tabelle (`code`, `name`, `active`, `created_at`), beim Startup aus
  `ACCESS_CODES` env geseedet (**fail-closed**: ohne Seed lehnt der Gate alles ab).
- `require_code`-Dependency prüft `X-Access-Code`-Header: fehlt → 401, ungültig/inaktiv
  → 403, gültig → Row. Validierter Code landet in `owner_code` bei Session-Erstellung
  (`owner_code` bleibt aus `/api/config/{id}` gefiltert).
- Gegatet: alle Endpunkte, die einen **bezahlten externen API-Call** auslösen oder eine
  Session erstellen (`POST /api/sessions`, `audio-block`, `text-block`, `approve-claims`,
  `fact-checks/resend`, `pipeline`-Retrigger). GETs + nicht-bezahlte Mutationen (`end`,
  pending-block-DELETE) bleiben offen — geteilte Privat-Links müssen ohne Code funktionieren.
- Frontend: Zugangscode-Feld im `/new`-Flow, Header aus `localStorage`, 401/403-Handling.
- **Provider-Budget-Caps** (AssemblyAI/Gemini/Tavily) als manueller Runbook-Schritt
  dokumentiert — das äußere Limit, das auch bei geleaktem Code hält.

**Bewusst NICHT in dieser Phase:** Quick Check, 10-Min-Auto-Stop, Circuit Breaker,
Per-Code-Kontingente, Admin-UI (Codes via DB/SQL verwaltet). Siehe Spec §Scope.

**Abhängigkeiten:** Phase 1 (`owner_code`-Spalte, Sessions-Router) — erfüllt.

---

## ✅ Phase R — Agent-Rewrite: LangChain → PydanticAI + Logfire (ABGESCHLOSSEN)

**Spec:** `docs/superpowers/specs/2026-06-10-pydanticai-agent-rewrite-design.md`
**Plan:** `docs/superpowers/plans/2026-06-10-pydanticai-agent-rewrite.md`
**Status:** Implementiert + verifiziert auf Branch `worktree-session-multitenancy` (2026-06-10,
11 Commits `3ebaad1`→`93aab77`). **NICHT nach main gemergt** — Merge = Go-Live (Phase 4).

**Was gebaut wurde:**
- Deps `langchain*`/`langgraph` → **pydantic-ai 1.74.0 + logfire 4.36.0**.
- Neue Module: `backend/services/llm_base.py` (`build_model(primary, fallback=None)` →
  GoogleModel/`FallbackModel`, `MODEL_SETTINGS=GoogleModelSettings(temperature=0)`),
  `search.py` (`tavily_search`-Tool über `tavily-python` direkt, Datumsfilter-Fallback erhalten),
  `observability.py` (`configure_logfire()`, `send_to_logfire="if-token-present"` → no-op ohne Token).
- `claim_extraction.py` neu auf PydanticAI (3 Agents: `speaker_resolver`, `claim_extractor`,
  `selection_agent` mit `deps_type` für `{max_claims}`); public API eingefroren.
- `fact_checker.py` neu: PydanticAI-Agent mit `tavily_search`-Tool + `UsageLimits(request_limit=
  FACT_CHECK_RECURSION_LIMIT)` (Loop/Retry) + separater `critique_agent`; public API eingefroren.
- Logfire in `app.py`-Lifespan verdrahtet. **Gelöscht:** `cost_tracker.py`, `studio_graph.py`,
  `mock_search.py`, `test_cost_tracker.py` (CostTracker-Rolle → Logfire-Spans/PydanticAI-`usage()`).
- Tests auf `TestModel`/`FunctionModel` umgestellt, `models.ALLOW_MODEL_REQUESTS=False` als Safety-Net.
- Self-Critique: als **eigener zweiter Agent** umgesetzt (annotiert nur, gated nie).
- `studio_graph.py` + `langgraph-cli` ersatzlos raus (Logfire übernimmt Tracing).

**Verifikation:** 188 Unit-Tests grün, ruff clean, Router unberührt. Integration-Gate mit echten
Keys: text-pipeline + single-claim passed (typed output, echte Tavily-Calls), audio skipped (kein
Fixture). Prod-Spot-Check (Claim #93, maischberger-2025-09-19, `gemini-2.5-pro`): neuer Verdict
`hoch` = Prod-Verdict, Quellen nur trusted domains. Logfire live verifiziert (Trace mit
`tavily_search`-Spans + FallbackModel-Chain + critique-Agent) gegen `mertensu/fact-check`;
`LOGFIRE_TOKEN` lokal in `.env` + auf VPS-`.env` vorgestaged (inert bis Phase-R-Deploy).

**Erkenntnisse:** Reviews fanden einen latenten Speaker-Label-`.replace`-Ordering-Bug (gefixt) +
einen aussagelosen Retry-Test (gehärtet). Modell `gemini-2.0-flash-lite` ist **retired (404)** —
Integration-Tests nutzen jetzt `gemini-2.5-flash`. Handover: `handover/2026-06-10_phase-r-pydanticai-rewrite.md`.

---

## ✅ Phase Q — Quick Check (ABGESCHLOSSEN)

**Spec:** `docs/superpowers/specs/2026-06-10-quick-check-design.md`
**Plan:** `docs/superpowers/plans/2026-06-10-quick-check.md`
**Status:** Implementiert + verifiziert auf Branch `worktree-session-multitenancy` (2026-06-10,
7 Commits `46c0b03`→`26561b9`). **NICHT nach main gemergt** — Merge = Go-Live (Phase 4).

**Ziel:** Niedrigschwelliger Einstieg: Nutzer fügt ein **Text-Zitat** ein → direkt durch
den `fact_checker` (Gemini + Tavily), ohne Audio/Transkription/Claim-Extraction.

**Was gebaut wurde:**
- Quota auf der `codes`-Tabelle: neue Spalten `quick_checks_used` / `quick_check_limit`
  (CREATE TABLE + idempotente ALTER-Migration für bestehende Prod-Tabellen),
  `add_code(..., quick_check_limit=3)`, `increment_quick_checks(code)`.
- `ACCESS_CODES`-Syntax erweitert: `name:code:limit` (absent → Default 3, `unlimited` → None/kein
  Cap, `<n>` → Custom-Cap); `parse_access_codes` liefert jetzt 3-Tupel, `seed_codes_from_env` reicht
  das Limit durch.
- **Synchroner** `POST /api/quick-check` (gegatet via `require_code`): prüft Kontingent VOR dem
  bezahlten Fact-Checker-Call (429 „Kontingent aufgebraucht"), reuse `check_claim_async` +
  `build_fact_check_dict`, persistiert unter `session_id="quick-<code>"`, zählt hoch, liefert
  `{fact_check, limit, remaining}` (remaining=None für unlimited/Owner).
- Frontend: `submitQuickCheck` / `fetchQuickCheckHistory` in `api.js`; neue `/pruefen`-Seite
  (`QuickCheckPage`, reuse `ClaimCard` + `ClaimDetailOverlay`) mit Quota-Anzeige + Verlauf der
  früheren Checks; Homepage-Link.
- Deployment-Doku: Quota-Syntax + VPS-Owner-Exemption-Runbook (`docs/deployment.md`).

**Verifikation:** 204 Unit-Tests grün, ruff clean, Frontend-Build ok. Pro Task Spec- + Code-Quality-
Review (subagent-driven); finaler holistischer Review = „ready to merge", nur kosmetische Notizen
(eine — Input-Reset bei Auth-Fehler — gefixt; fehlende CSS-Klassen bewusst out-of-scope = Phase 1b).

**Bewusst NICHT in dieser Phase:** Background/Polling (Endpunkt ist synchron), Zwei-Button-Homepage-
Redesign (→ Phase 1b), Edit/Resend von Quick Checks. **Abhängigkeiten:** Phase 3a (Gate) — erfüllt.

---

## ⬜ Phase 3b — Live-Limits (eigener Spec)

**Ziel:** Kosten-Backstop für Live-Sessions. **10-Min-Auto-Stop** (Session endet nach
10 Min Aktivität automatisch); optional später globaler Circuit Breaker.

**Abhängigkeiten:** sinnvoll zusammen mit Phase 2 (Browser-Audio).

---

## 🟡 Phase 4 — VPS-Deployment (Backend live; Go-Live-Merge offen)

**Status (2026-06-09):** Part A (Code) + Part B (Betrieb) abgeschlossen auf Branch
`worktree-session-multitenancy`. Das Backend läuft live auf dem VPS als zwei systemd-Services
(`factcheck-backend` + `cloudflared`); `https://api.live-faktencheck.de/api/health` liefert
`status: ok`, `fact_checks: 241`, übersteht Reboots, tägliches DB-Backup-Cron aktiv. CLI-
verifiziert: `/api/config/shows` (nur public), `/api/trusted-domains`, CORS für `*.pages.dev`.
**Offen:** Pages-**Preview**-Smoke-Test im Browser (Cloudflare-Dashboard-Schritte) und der
optionale **Go-Live-Merge** nach `main` (schaltet das Prod-Frontend auf die Live-API um).
Tunnel bleibt bewusst bestehen (Option A) — der ursprünglich geplante DNS-A-Record entfällt.
Details: `plans/2026-06-09-phase4-vps-deployment.md`, Handover `handover/2026-06-09_*`.

**Ziel:** Backend dauerhaft auf dem Hostinger-VPS — kein lokaler Start.

**Technische Eckpunkte:**
- Backend als `systemd`-Service (oder Docker) auf dem VPS; eigene öffentliche IP.
- DNS: `api.live-faktencheck.de` als A-Record auf die VPS-IP (Tunnel löschen).
  TLS via Caddy/nginx + Let's Encrypt oder Cloudflare-Proxy.
- Frontend bleibt auf Cloudflare Pages; nur `VITE_BACKEND_URL` zeigt auf die neue API.
- CORS in `backend/app.py` ggf. anpassen.
- **JSON-Export entfällt:** Sobald das Backend erreichbar ist, liest das Frontend live
  über die API. `export_episode.py` und der Re-Export-Workflow werden überflüssig
  (siehe Spec §2a). Cleanup als Teil dieser Phase.
- `start_production.sh` / Tunnel-Setup-Doks anpassen oder ersetzen.

**Abhängigkeiten:** unabhängig; kann jederzeit nach Phase 1 erfolgen. Sinnvoll früh,
da es den ursprünglichen Schmerzpunkt („muss lokal starten") direkt löst.

---

## Empfohlene Reihenfolge

1. ~~**Phase 3a (Zugangs-Gate)**~~ — ✅ erledigt, live auf VPS (2026-06-10).
2. ~~**Phase R (Agent-Rewrite PydanticAI + Logfire)**~~ — ✅ erledigt auf Branch (2026-06-10).
3. ~~**Phase Q (Quick Check)**~~ — ✅ erledigt auf Branch (2026-06-10). Schnellster Weg zu einem
   nutzbaren Produkt, baut auf dem (rewritten) Agenten auf.
4. ~~**Phase 1b (Homepage/IA)**~~ — ✅ erledigt auf Branch (2026-06-10). Einzelne Landing-Page mit
   beiden Einstiegs-Modi (Quick Check + Live) + Beispiele-Archiv.
5. **Phase 2 (Browser-Audio)** — macht die Live-Mode ohne lokales `listener.py` nutzbar. **← nächster Schritt.**
6. **Phase 3b (Live-Limits)** — 10-Min-Auto-Stop, zusammen mit/nach Phase 2.
7. **Phase 4 (Go-Live-Merge)** — Branch → main; Gate + Agent-Rewrite stehen bereits. Aktiviert
   beim Deploy auch die Phase-R-Logfire-Observability (Token auf VPS bereits vorgestaged).

## Wiedereinstieg

- Diesen Branch auschecken: `git checkout worktree-session-multitenancy`
  (bzw. der Worktree unter `.claude/worktrees/session-multitenancy`).
- Für die nächste Phase: Brainstorming-Skill → Spec nach
  `docs/superpowers/specs/` → Plan nach `docs/superpowers/plans/`.
