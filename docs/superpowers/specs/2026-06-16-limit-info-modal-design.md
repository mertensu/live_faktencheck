# Limit-Hinweis-Popup nach Freischaltung

**Datum:** 2026-06-16
**Status:** Genehmigt

## Ziel

Nachdem ein Nutzer einen Zugangscode eingibt und freischaltet, ploppt ein Fenster
auf, das über die Limits seines Codes informiert (z. B. Standard-User: max. 3
Behauptungen, 5 Minuten Live-Audio).

## Verhalten

- Erscheint **nur direkt nach erfolgreicher Code-Eingabe** (aktiver `handleSubmit`-Pfad
  in `AccessUnlock`), **nicht** beim automatischen Freischalten via gespeichertem Code
  (Seiten-Reload).
- Schließbar per Button, Klick auf den Backdrop und `Esc` — analog zu
  `ClaimDetailOverlay`.
- Keine Persistenz, kein „nicht mehr anzeigen"-Häkchen.

## Datenquelle (Backend)

- `/validate-code` (`backend/routers/config.py`) wird um Felder erweitert:
  - `audio_seconds_limit` (bereits im `code`-Dict via `auth.py` vorhanden)
  - `audio_limit_minutes` (abgeleiteter Komfortwert für die Anzeige)
- `quick_check_limit` liefert der Endpoint bereits.
- Ein Limit von `null` ⇒ Anzeige **„unbegrenzt"** (gilt für `unlimited`-Codes).

## Frontend

- Neue Komponente `frontend/src/components/LimitInfoModal.jsx`
  (Backdrop + Panel, gleiche CSS-Konvention wie `ClaimDetailOverlay`). Inhalt:
  - Titel: „Freigeschaltet" (+ Name, falls vorhanden)
  - 🔎 **Behauptungen prüfen:** max. *N* (bzw. „unbegrenzt")
  - 🎙 **Live-Audio:** *M* Minuten (bzw. „unbegrenzt")
  - Kurzer Hinweissatz + „Verstanden"-Button
- `AccessUnlock` reicht die vollständigen Validierungsdaten nach oben weiter:
  `onUnlock(code, name, data)`.
- `HomePage` hält `limitInfo`-State, öffnet das Modal nur bei echtem Unlock aus
  Eingabe und rendert `<LimitInfoModal>`.

## Tests

- Backend: `backend/tests/test_access_gate.py` um die neuen Response-Felder erweitern.
- Frontend: `cd frontend && bun run build` muss durchlaufen.

## Bewusst weggelassen (YAGNI)

- Kein „nicht mehr anzeigen"-Häkchen.
- Kein Anzeigen des bereits verbrauchten Stands (`quick_checks_used`).
- Keine Persistenz über Sessions hinweg.
