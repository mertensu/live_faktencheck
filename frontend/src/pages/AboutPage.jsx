import { useState } from 'react'
import { WorkflowDiagram } from '../components/WorkflowDiagram'

export function AboutPage() {
  const [diagramOpen, setDiagramOpen] = useState(false)

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Über live-faktencheck.de</h1>
        <p>
          In unserer digitalisierten Welt sind wir tagtäglich mit einer Flut an Informationen konfrontiert.
          Die Algorithmen der sozialen Medien filtern diese und begünstigen das Aufsehenerregende, darunter populistische,
          extreme und emotional aufgeladene Ansichten. Gleichermaßen nimmt das wissenschaftlich Nüchterne und
          Faktenbasierte durch den fehlenden Polarisierungscharakter eine untergeordnete Rolle ein. Aufgrund der
          Schnelllebigkeit des Internets können sich so Behauptungen oder Ansichten, ohne eine entsprechende
          fundierte Einordnung oder gar Richtigstellung, rasant verbreiten und festsetzen. Ein umfangreiches,
          gründliches Überprüfen ist mühsam, erfordert
          Expertise und kostet Zeit und findet daher nur sporadisch statt.
        </p>
        <p>
          Mit diesem Projekt möchte ich einen kleinen Beitrag liefern, um dieser Dynamik etwas entgegensetzen.
          live-faktencheck.de ist eine Plattform, die Aussagen aus Talkshows oder Interviews live* auf ihre
          empirische Untermauerung prüft. Mithilfe von künstlicher Intelligenz wird dabei eine Einstufung der Vertrauenswürdigkeit und eine ausführliche Begründung der
          Entscheidungsfindung vorgenommen. Darüberhinaus werden die der Entscheidung zugrunde liegenden Quellen angegeben. Um die Gefahr von Halluzinationen des
          Sprachmodells, also dem Erzeugen einer plausiblen aber falschen Begründung, zu minimieren, findet
          eine gerichtete, iterative Web-Recherche statt. Das Modell wird gezwungen, eine Liste an
          vertrauenswürdigen Seiten/Domains bei der Suche zu priorisieren (<a href="/trusted-domains">siehe hier</a>).
        </p>
        <p>
          Ich möchte betonen, dass bei diesem Projekt großer Wert auf politische Neutralität gelegt wird und
          in keiner Weise diskreditiert oder diffamiert werden soll. Es geht vielmehr darum, aufzuzeigen,
          wie sehr bestimmte Behauptungen durch Studien, Statistiken oder andere vertrauenswürdige Quellen
          gestützt werden. Das gesamte laufende Projekt ist{' '}
          <a href="https://github.com/mertensu/live_faktencheck">vollständig zugänglich</a> und ich möchte
          alle herzlich einladen mitzuwirken.
        </p>
        <p>
          Nicht zuletzt sei betont, dass dieses Projekt in den Anfängen steht und Fehler bzw. Ungenauigkeiten nicht ausgeschlossen werden können. Bei Fragen, Anmerkungen oder Verbesserungsvorschlägen wenden Sie sich gerne jederzeit an <a href="mailto:info@live-faktencheck.de">info@live-faktencheck.de</a>
        </p>
        <p><small>*mit einer Verzögerung von wenigen (&lt; 5) Minuten</small></p>
        <h2>Wie es funktioniert</h2>
        <div className="diagram-desktop">
          <WorkflowDiagram />
        </div>
        <button className="diagram-show-btn" onClick={() => setDiagramOpen(true)}>
          Ablauf als Diagramm anzeigen ↗
        </button>

        {diagramOpen && (
          <div className="diagram-modal-overlay" onClick={() => setDiagramOpen(false)}>
            <button className="diagram-modal-close" onClick={() => setDiagramOpen(false)}>✕ Schließen</button>
            <div className="diagram-modal-inner" onClick={e => e.stopPropagation()}>
              <WorkflowDiagram />
            </div>
          </div>
        )}
        <p>
          Die Sendungen werden in zeitlich begrenzte Blöcke aufgeteilt und dann live transkribiert. Das Transkript wird im Anschluss an ein großes Sprachmodell (LLM) weitergereicht,
          welches überprüfbare Behauptungen extrahiert und diese automatisch den jeweiligen Sprechern zuweist. Ein Moderator prüft diese Aussagen auf Relevanz und stilistische Korrektheit und gibt sie schließlich
          einem weiteren KI-Agenten zur Bewertung frei. Es folgt ein iterativer Prozess, bei dem im Web nach relevanten Statistiken und Daten gesucht wird —
          beschränkt auf vertrauenswürdige Quellen wie offizielle Regierungsseiten oder anerkannte Institute —,
          diese Informationen dann mit Blick auf die Aussagen eingeordnet werden und, sofern keine erschöpfende
          Schlussfolgerung möglich ist, ein weiterer Recherche-Block folgt. Das Modell nimmt eine Bewertung vor (wie sehr wird die Aussage durch Daten gestützt),
          gibt eine ausführliche Erklärung ab sowie die der Entscheidung zugrunde liegenden Quellen an. Für Details sei auf das <a href="https://github.com/mertensu/live_faktencheck">Github-Projekt</a> verwiesen.
        </p>
        <h2>Hinweis</h2>
        <p>
          Die hier dargestellten Fakten-Checks werden automatisch mit Hilfe von
          künstlicher Intelligenz (KI) generiert. Die Inhalte können Fehler enthalten
          und sollten daher als Orientierungshilfe, nicht jedoch als alleinige Quelle zur Meinungsbildung herangezogen werden.
        </p>
      </div>
    </div>
  )
}
