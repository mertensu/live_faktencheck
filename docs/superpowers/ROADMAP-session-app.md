# Roadmap — Von „Live Faktencheck" zur Multi-User-App

**Stand:** 2026-06-09
**Branch dieser Arbeit:** `worktree-session-multitenancy` (Phase 1, abgeschlossen)

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
| **1b** | Homepage / App-Informationsarchitektur neu denken | ⬜ Offen (eigener Spec) |
| **2** | Browser-Audio-Capture (ersetzt `listener.py`) | ⬜ Offen |
| **3a** | **Minimaler Zugangs-Gate (Zugangscodes auf Kosten-Endpunkten)** | ✅ **Live auf VPS** (2026-06-10, `971a7de`; main-Merge offen) |
| **R** | **Agent-Rewrite: LangChain/LangGraph → PydanticAI + Logfire** | ⬜ Offen (eigener Spec) |
| **Q** | Quick Check (One-Shot-Zitat → Fact-Check, ohne Audio) | ⬜ Offen (eigener Spec) |
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

## ⬜ Phase 1b — Homepage / Informationsarchitektur

**Warum:** Sobald Sessions privat/per-Link sind, verliert die Startseite ihren
„Schaufenster"-Zweck (Live-Faktenchecks präsentieren). Sie braucht eine neue Aufgabe.

**Offene Designfragen (für Brainstorming):**
- Was ist die primäre Aufgabe der Startseite? Wahrscheinlich: Produkt erklären +
  Einstieg „Eigene Session starten" (Code eingeben → Session-Formular).
- Wie werden die Legacy-Episoden (öffentlich) künftig dargestellt — eigener
  „Beispiele/Archiv"-Bereich?
- Navigation/IA der ganzen App: Create-Flow, Live-Ansicht, geteilte Link-Ansicht,
  Archiv, About.
- Visual-Companion (Mockups) bietet sich hier an, da stark visuell.

**Abhängigkeiten:** keine harten; kann unabhängig von Phase 2–4 entworfen werden.
In Phase 1 wurde die Homepage bewusst NICHT angefasst (nur `/new` ergänzt).

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

## ⬜ Phase R — Agent-Rewrite: LangChain → PydanticAI + Logfire (eigener Spec)

**Ziel:** Den Fact-Check-Agenten weg vom LangChain/LangGraph-Universum auf **PydanticAI**
(Agent/Tools/Structured Output) + **Logfire** (Observability) umstellen.

**Heutiger LangChain-Footprint (zu migrieren):**
- `backend/services/fact_checker.py` — Kern: LangGraph-ReAct-Agent (`create_agent`),
  `ChatGoogleGenerativeAI` (primär + Fallback via `with_fallbacks`), `TavilySearch` +
  `FallbackSearchTool` (Retry ohne Datumsfilter), Self-Critique-Schritt, Recursion-Trace-Dump.
- `backend/services/studio_graph.py` — LangGraph-Studio-Graph (Dev-Visualisierung).
- Deps: `langchain`, `langchain-google-genai`, `langchain-tavily`, `langgraph` (+ `langgraph-cli`).
- **Nicht betroffen:** `claim_extraction.py` nutzt bereits `google-genai` direkt (kein LangChain);
  Output-Modelle (`FactCheckResponse`, `Source`, `SelfCritiqueResponse`, `ClaimInput`) sind schon
  reines Pydantic → von PydanticAI direkt nutzbar.

**Offene Designfragen (fürs Brainstorming):**
- Modell/Provider: PydanticAI-Gemini-Provider; **`FallbackModel`** für Primär→Fallback statt
  `with_fallbacks`. Welche Gemini-Modelle (heute `gemini-2.5-pro`)?
- Tavily als PydanticAI-Tool über `tavily-python` direkt (drop `langchain-tavily`); die
  `FallbackSearchTool`-Retry-Logik (leeres Ergebnis → ohne Datumsfilter) erhalten.
- **Logfire vs. `CostTracker`:** ersetzt/ergänzt Logfire den bestehenden `cost_tracker.py`?
  (Token-Usage kommt über PydanticAI-`usage()`/Logfire-Spans.) Logfire-Token = neue env/Account.
- Self-Critique: eigener zweiter PydanticAI-Agent oder integriert?
- `studio_graph.py` + `langgraph-cli` ersatzlos raus (Logfire übernimmt Tracing)?
- Tests: `test_fact_checker.py` + conftest-Mocks (FactCheckResponse etc.) neu schreiben
  (PydanticAI-`TestModel`/`FunctionModel` statt LangChain-Mocks).

**Abhängigkeiten/Reihenfolge:** unabhängig von 2/3b; **sinnvoll VOR Phase Q**, weil Quick Check
denselben `fact_checker`-Service wiederverwendet — sonst würde Q erst auf LangChain gebaut und
dann mitmigriert. Risiko: Kern-Logik des Backends; nach Rewrite gründlich gegen Live-Verhalten
verifizieren (Integration-Tests mit echten Keys).

---

## ⬜ Phase Q — Quick Check (eigener Spec)

**Ziel:** Niedrigschwelliger Einstieg: Nutzer fügt ein **Text-Zitat** ein → direkt durch
den `fact_checker` (Gemini + Tavily), ohne Audio/Transkription/Claim-Extraction.

**Eckpunkte (noch zu entwerfen):** eigener Endpunkt (reuse `fact_checker`-Service),
code-gegatet wie 3a, **Kontingent: 3 Quick-Checks pro Code (lifetime, gezählt via
`owner_code`)**. Ergebnis-Darstellung über bestehendes `ClaimCard`. Unabhängig von Phase 2
→ schnellster Weg zu einem nutzbaren Produkt.

**Abhängigkeiten:** Phase 3a (Gate). Brainstorming/Spec stehen noch aus.

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
2. **Phase R (Agent-Rewrite PydanticAI + Logfire)** — VOR Phase Q, da Quick Check denselben
   `fact_checker`-Service nutzt. Eigener Spec.
3. **Phase Q (Quick Check)** — schnellster Weg zu einem nutzbaren Produkt, unabhängig von
   Browser-Audio. Baut auf dem (rewritten) Agenten auf.
4. **Phase 2 (Browser-Audio)** — macht die Live-Mode ohne lokales `listener.py` nutzbar.
5. **Phase 3b (Live-Limits)** — 10-Min-Auto-Stop, zusammen mit/nach Phase 2.
6. **Phase 1b (Homepage/IA)** — wenn beide Einstiegs-Modi (Quick Check + Live) stehen.
7. **Phase 4 (Go-Live-Merge)** — Branch → main; Gate steht bereits.

(Reihenfolge ist nicht zwingend; 1b kann parallel entworfen werden.)

## Wiedereinstieg

- Diesen Branch auschecken: `git checkout worktree-session-multitenancy`
  (bzw. der Worktree unter `.claude/worktrees/session-multitenancy`).
- Für die nächste Phase: Brainstorming-Skill → Spec nach
  `docs/superpowers/specs/` → Plan nach `docs/superpowers/plans/`.
