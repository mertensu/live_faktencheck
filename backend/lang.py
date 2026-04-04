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

CONSISTENCY_DESCRIPTION = """Empirische Konsistenz der Behauptung. Wähle genau eine von vier Stufen:
- 'hoch': Die verfügbaren Daten stützen die Behauptung — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind.
- 'niedrig': Die verfügbaren Daten widersprechen der Behauptung — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind.
- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar.
- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden."""
EVIDENCE_DESCRIPTION = "Detaillierte und gut strukturierte deutschsprachige Begründung"
SOURCES_DESCRIPTION = "Primärquellen mit URL und kurzem informativem Titel"

# --- Self-critique response schema ---
CRITIQUE_CONFIDENCE_DESCRIPTION = (
    "'high' = Urteil ist klar und gut belegt; eine erneute Recherche würde dasselbe Ergebnis liefern. "
    "'low' = Urteil ist mit Unsicherheit behaftet; die Begründung ist nicht vollständig schlüssig "
    "bzw. lässt Spielraum für alternative Interpretationen."
)
CRITIQUE_REASON_DESCRIPTION = (
    "Kurze und prägnante deutschsprachige Erklärung, warum das Urteil (nicht) robust ist. Immer ausfüllen."
)
