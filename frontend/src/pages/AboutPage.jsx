import { WorkflowDiagram } from '../components/WorkflowDiagram'

export function AboutPage() {
  const isProduction = import.meta.env.PROD

  // Production: show coming soon message
  if (isProduction) {
    return (
      <div className="about-page">
        <div className="about-content">
          <h1>Über live-faktencheck.de</h1>
          <p>
            Weitere Informationen folgen in Kürze.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Über live-faktencheck.de</h1>
        <p>
          Schon seit Langem wird der Wunsch nach einem Live-Faktencheck geäußert. Mit der rasanten Entwicklung im Bereich
          „Künstliche Intelligenz" (KI) steht einer Realisierung nun nichts mehr im Wege. Zwar ist die Idee eines KI-gesteuerten
          Faktenchecks nicht neu, und Ansätze existieren. Nach meinem Wissen sind diese Projekte allerdings über einen ersten
          Machbarkeitsnachweis (Proof-of-Concept) nicht herausgekommen.
          live-faktencheck.de ändert das. BesucherInnen können nahezu live verfolgen (derzeit mit wenigen Minuten Verzögerung),
          wie getätigte Aussagen der anwesenden Gäste überprüft werden, und erhalten im Anschluss eine Einstufung, wie sehr die
          jeweilige Aussage durch Daten und Fakten gestützt ist, sowie eine ausführliche Begründung der Einordnung und recherchierte Quellen.
          <br />
          Ich möchte betonen, dass es hier ausdrücklich nicht darum geht, die Gäste bzw. Content-Creator an den Pranger zu stellen, zu diskreditieren oder in sonstiger Weise
          in Verruf zu bringen. Es geht vielmehr darum, aufzuzeigen, wie sehr bestimmte Behauptungen durch Studien, Statistiken oder andere vertrauenswürdige Quellen gestützt werden.
          Somit bleiben die Aussagen nicht undiskutiert im Raum stehen, sondern werden einer (ersten) kritischen Betrachtung unterzogen, und zwar während die Sendung läuft.
        </p>
        <h2>Wie es funktioniert</h2>
        <WorkflowDiagram />
        <p>
          Die Sendungen werden in zeitlich begrenzte Blöcke aufgeteilt und dann live transkribiert. Diese Transkripte werden an ein großes Sprachmodell (LLM) weitergereicht,
          welches überprüfbare Behauptungen extrahiert und diese automatisch den jeweiligen Sprechern zuweist. Diese Aussagen werden daraufhin auf Relevanz und Korrektheit geprüft und schließlich
          einem weiteren Agenten (LLM) zur Bewertung übergeben. Es folgt ein iterativer Prozess, bei dem im Web nach relevanten Statistiken und Daten gesucht wird —
          beschränkt auf vertrauenswürdige Quellen wie offizielle Regierungsseiten oder anerkannte Institute —,
          diese Informationen dann mit Blick auf die Aussagen eingeordnet werden und, sofern keine erschöpfende
          Schlussfolgerung möglich ist, ein weiterer Recherche-Block folgt. Das Modell nimmt eine Bewertung vor (wie sehr wird die Aussage durch Daten gestützt),
          gibt eine ausführliche Erklärung ab sowie die der Entscheidung zugrunde liegenden Quellen an. Für Details sei auf das <a href="https://github.com/mertensu/live_faktencheck">Github-Repository</a> verwiesen.
        </p>
        <h2>Hinweis</h2>
        <p>
          Die hier dargestellten Fakten-Checks werden automatisch mit Hilfe von
          künstlicher Intelligenz (KI) generiert. Die Inhalte können Fehler enthalten
          und sollten nicht als alleinige Grundlage für Entscheidungen verwendet werden.
        </p>
      </div>
    </div>
  )
}
