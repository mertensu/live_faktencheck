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
- Nenne im Text nie Zeitungen, Zeitschriften oder Sender, auch nicht aus eigenem Wissen. [Hinweis]-Treffer sind keine Belege: Sie dürfen zeigen, woher eine Zahl stammt (Studie, Institut, Person) oder wer ihr widerspricht. Nenne dann allein diesen Urheber („nach einer Rechnung von …“), nie den Hinweis als Fundort, und sag, dass dessen Originalquelle nicht vorliegt, falls sie fehlt.
- Bei 'unklar' oder 'keine Datenlage': sag knapp, was fehlt oder nicht passt."""

CONSISTENCY_DESCRIPTION = """Empirische Konsistenz des Kerns der Behauptung: der zentralen Tatsache oder Zahl. Eine ausdrücklich behauptete Ursache („dadurch“, „wegen“, „hat dazu geführt“) gehört zum Kern; eine Zeitangabe wie „unter Minister X“ beschreibt nur den Zeitraum. Wähle genau eine von vier Stufen:
- 'hoch': Die Daten stützen den Kern — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind. Nebenaspekte, zu denen die Treffer nichts sagen, senken die Stufe nicht. Eine behauptete Ursache muss belegt sein: Zeigen die Daten nur die Entwicklung, nicht die Ursache, ist das 'unklar'.
- 'niedrig': Die Daten widersprechen dem Kern — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind. Widerlegen die Daten schon die behauptete Tatsache, ist das 'niedrig', auch wenn zusätzlich eine Ursache behauptet wird. Absolute Aussagen („keinerlei“, „alle“, „nie“, „höchste aller Zeiten“) sind widerlegt, sobald ein belastbarer Treffer das Gegenteil zeigt.
- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar.
- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden."""

SOURCES_DESCRIPTION = """Die Treffer, auf die sich die Einschätzung stützt, in der Regel 1–3; keine, die das Thema nur streifen. Nur URLs, die in den Suchergebnissen vorkommen; leere Liste, wenn keine relevanten Quellen vorliegen.
- Die Treffer sind markiert und in dieser Reihenfolge sortiert: [amtlich], [Forschung], [Land], [Hinweis], [Partei].
- [Land] sind Landesbehörden, -statistikämter und Landtage: erste Wahl, wenn die Behauptung ein bestimmtes Bundesland betrifft; bei Deutschland insgesamt oder der EU nur, wenn kein [amtlich]- oder [Forschung]-Treffer die Aussage trägt.
- [Hinweis]-Treffer haben keine URL und werden nie aufgeführt.
- [Partei]-Treffer sind Positionen, keine Belege — nur aufführen, wenn die Behauptung selbst eine Parteiposition betrifft."""

REFERENCED_DOCUMENTS_DESCRIPTION = """Offizielle Dokumente, Studien oder Berichte, die in den Suchergebnissen genannt oder zitiert werden und die Behauptung direkt beantworten würden, deren Inhalt aber nicht (oder nur angerissen) in den Treffern steht — z. B. ein Finanzplan, ein amtlicher Bericht, ein Gutachten, eine Studie. Je Eintrag der Titel so, wie er genannt wird, mit Herausgeber und Jahr (z. B. „Finanzplan des Bundes 2025 bis 2029“, „Monitoringbericht 2025 Bundesnetzagentur“); Dokumente internationaler Stellen (Eurostat, OECD, IEA, EU-Kommission) mit ihrem englischen Titel. Höchstens 2; leere Liste, wenn keins genannt wird oder die Treffer die Behauptung schon beantworten."""

# --- Agent fact-check schema (AgentFactChecker) ---
# The deep checker's original definitions (v0.2.0), with which the agent was measured;
# the fast check's sharper rules above are written for a single synthesis call.
AGENT_CONSISTENCY_DESCRIPTION = """Empirische Konsistenz der Behauptung. Wähle genau eine von vier Stufen:
- 'hoch': Die verfügbaren Daten stützen die Behauptung — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind. Eine ausdrücklich behauptete Ursache („dadurch“, „wegen“, „X hat Y bewirkt“) muss selbst belegt sein: Zeigen die Daten nur die Entwicklung, nicht die Ursache, ist das 'unklar'.
- 'niedrig': Die verfügbaren Daten widersprechen der Behauptung — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind.
- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar.
- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden."""
# The three texts of the reasoning; the UI shows kurz first, then the other two under
# fixed headings ("Was die Quellen sagen", "Was offen bleibt").
_AGENT_TEXT_RULES = """
- Nur was in den Suchtreffern steht; kein eigenes Wissen. Fehlt etwas, sag, dass die geprüften Quellen es nicht belegen.
- Für sich verständlich für Leser, die nur die Behauptung und diese Begründung sehen und von der Recherche nichts wissen: keine Wörter wie „Treffer“, „Suchtreffer“, „Suche“ oder „Auszug“ — sag „die geprüften Quellen“ oder nenne den Urheber. Wenig bekannte Abkürzungen beim ersten Nennen ausschreiben.
- Unpersönlich formuliert, nie in der Ich-Form („habe ich addiert“, „lag mir nicht vor“): Eigene Rechnungen kennzeichnest du als Rechnung („zusammengerechnet“, „daraus ergibt sich“).
- Flüssig formuliert, ohne Aufzählungszeichen oder Überschriften im Text.
- Gutes, eloquentes Deutsch wie in einer Nachrichtenredaktion."""
AGENT_KURZ_DESCRIPTION = """Das Ergebnis in 1–2 Sätzen, höchstens 250 Zeichen: was an der Behauptung belegt ist und was nicht, mit der entscheidenden Zahl oder Tatsache und ihrem Urheber. Steht über den beiden anderen Texten.""" + _AGENT_TEXT_RULES
AGENT_EVIDENCE_DESCRIPTION = """Was die Quellen sagen: die Belege, höchstens 800 Zeichen, ein bis zwei Absätze (getrennt durch eine Leerzeile). Nach Gedanken geordnet statt Quelle für Quelle: Zahlen mit Stand und Urheber im Satz, Quellen, die dasselbe sagen, zusammen, und wie das zur Behauptung passt. Sätze mit Verbindungen („weil“, „dagegen“, „allerdings“) statt aneinandergereihter Einzelaussagen. Wiederhole nicht das Ergebnis aus der Kurzfassung.""" + _AGENT_TEXT_RULES
AGENT_OPEN_DESCRIPTION = """Was offen bleibt: Einschränkungen, Gegenbelege, abweichende Zeiträume oder Abgrenzungen, fehlende Daten; höchstens 400 Zeichen. Leer lassen, wenn nichts Wesentliches offen ist. Nicht mit „Offen bleibt“ beginnen — das steht als Überschrift darüber.""" + _AGENT_TEXT_RULES
AGENT_SOURCES_DESCRIPTION = "Pflichtfeld: die 1–4 Primärquellen aus den Suchergebnissen, auf die sich Kurzfassung und Begründung stützen, je mit URL und kurzem informativem Titel. Leer nur bei 'keine Datenlage'."

# --- Live speakers ---
# Shown when a live claim cannot be tied to a diarization label — preferred over a name
# guessed from the text.
UNCLEAR_SPEAKER = "Unklar"
# The operator's pick for a voice that belongs to no guest — mostly a clip (Einspieler)
# with other people speaking. Neither gated nor checked.
OTHER_VOICE = "Andere Stimme"
