"""
Language strings for LLM-facing field descriptions.
To adapt this project for another language, change the strings in this file.
"""

# --- Claim extraction schema ---
CLAIM_NAME_DESCRIPTION = "Vollständiger Name des Sprechers (Eigenname)."
CLAIM_TEXT_DESCRIPTION = "Die deutschsprachige dekontextualisierte Behauptung."

# --- Fact-check response schema ---
SOURCE_URL_DESCRIPTION = "URL zur Quelle"
SOURCE_TITLE_DESCRIPTION = "Kurze informative Beschreibung der Quelle, z.B. 'Statistisches Bundesamt - Bevölkerungsdaten 2024'"

EVIDENCE_DESCRIPTION = """Kurze deutschsprachige Einschätzung, ein, höchstens zwei Sätze: die entscheidende Zahl oder Tatsache mit Stand (Jahr/Monat) und Quelle, z. B. „Laut Destatis lag … 2025 bei …“.
- Nenne als Quelle nur, wo du die Angabe gelesen hast — einen Treffer, den du unter ``sources`` aufführst. Steht eine Destatis-Zahl nur in einer Studie des IW, schreibe „laut IW (unter Berufung auf Destatis)“, nicht „laut Destatis“.
- Nenne nie Zeitungen, Zeitschriften oder Sender als Quelle, auch nicht aus eigenem Wissen.
- Bei 'unklar' oder 'keine Datenlage': sag knapp, was fehlt oder nicht passt."""

CONSISTENCY_DESCRIPTION = """Empirische Konsistenz des Kerns der Behauptung: der zentralen Tatsache oder Zahl. Eine ausdrücklich behauptete Ursache („dadurch“, „wegen“, „hat dazu geführt“) gehört zum Kern; eine Zeitangabe wie „unter Minister X“ beschreibt nur den Zeitraum. Wähle genau eine von vier Stufen:
- 'hoch': Die Daten stützen den Kern — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind. Nebenaspekte, zu denen die Treffer nichts sagen, senken die Stufe nicht. Eine behauptete Ursache muss belegt sein: Zeigen die Daten nur die Entwicklung, nicht die Ursache, ist das 'unklar'.
- 'niedrig': Die Daten widersprechen dem Kern — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind. Widerlegen die Daten schon die behauptete Tatsache, ist das 'niedrig', auch wenn zusätzlich eine Ursache behauptet wird. Absolute Aussagen („keinerlei“, „alle“, „nie“, „höchste aller Zeiten“) sind widerlegt, sobald ein belastbarer Treffer das Gegenteil zeigt.
- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar.
- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden."""

SOURCES_DESCRIPTION = """Die Treffer, auf die sich die Einschätzung stützt, in der Regel 1–3; keine, die das Thema nur streifen. Nur URLs, die in den Suchergebnissen vorkommen; leere Liste, wenn keine relevanten Quellen vorliegen.
- Die Treffer sind markiert und in dieser Reihenfolge sortiert: [amtlich], [Forschung], [Land], [Partei].
- [Land] sind Landesbehörden, -statistikämter und Landtage: erste Wahl, wenn die Behauptung ein bestimmtes Bundesland betrifft; bei Deutschland insgesamt oder der EU nur, wenn kein [amtlich]- oder [Forschung]-Treffer die Aussage trägt.
- [Partei]-Treffer sind Positionen, keine Belege — nur aufführen, wenn die Behauptung selbst eine Parteiposition betrifft."""

# --- Live speakers ---
# Shown when a live claim cannot be tied to a diarization label — preferred over a name
# guessed from the text.
UNCLEAR_SPEAKER = "Unklar"
