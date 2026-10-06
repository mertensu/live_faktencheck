import { PipelineAnimation } from '../components/PipelineAnimation'

export function AboutPage() {
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
          empirische Untermauerung prüft. Der Fokus liegt dabei bewusst auf politischen und gesellschaftlichen
          Debatten. Mithilfe von künstlicher Intelligenz wird dabei eine Einstufung der Vertrauenswürdigkeit samt
          kurzer Begründung vorgenommen; zusätzlich werden die der Entscheidung zugrunde liegenden Quellen angegeben.
          Um die Gefahr von Halluzinationen des Sprachmodells, also dem Erzeugen einer plausiblen aber falschen
          Begründung, zu minimieren, stützt sich jede Bewertung auf eine gezielte Web-Recherche. Das Modell wird
          dabei gezwungen, eine Liste an vertrauenswürdigen Seiten/Domains bei der Suche zu priorisieren
          (<a href="/trusted-domains">siehe hier</a>), und darf nur Quellen nennen, die es tatsächlich gefunden hat.
        </p>
        <p>
          Ich möchte betonen, dass bei diesem Projekt großer Wert auf politische Neutralität gelegt wird und
          in keiner Weise diskreditiert oder diffamiert werden soll. Es geht vielmehr darum, aufzuzeigen,
          wie sehr bestimmte Behauptungen durch Studien, Statistiken oder andere vertrauenswürdige Quellen
          gestützt werden. Der Quellcode des Projekts ist{' '}
          <a href="https://github.com/mertensu/live_faktencheck">quelloffen einsehbar</a> (unter einer
          nicht-kommerziellen Lizenz); über Rückmeldungen und Hinweise freue ich mich jederzeit.
        </p>
        <p>
          Nicht zuletzt sei betont, dass dieses Projekt in den Anfängen steht und Fehler bzw. Ungenauigkeiten nicht ausgeschlossen werden können. Bei Fragen, Anmerkungen oder Verbesserungsvorschlägen wenden Sie sich gerne jederzeit an <a href="mailto:info@live-faktencheck.de">info@live-faktencheck.de</a>
        </p>
        <p><small>*mit einer Verzögerung von wenigen Sekunden</small></p>
        <h2>Wie es funktioniert</h2>
        <PipelineAnimation />
        <p>
          Der Ton der Sendung wird fortlaufend an einen Transkriptionsdienst gestreamt und erscheint Satz für Satz
          als Live-Transkript. Ein schnelles KI-Modell entscheidet für jeden Satz, ob er eine überprüfbare und
          relevante Tatsachenbehauptung enthält. Ist das der Fall, formuliert ein Sprachmodell (LLM) den Satz
          als eigenständige Aussage um – mit Blick auf die vorangegangenen Sätze, damit etwa „das“ oder „dort“
          aufgelöst werden – und leitet daraus mehrere Suchanfragen ab. Diese laufen parallel im Web, beschränkt auf
          vertrauenswürdige Quellen wie offizielle Statistikämter, Ministerien oder anerkannte Forschungsinstitute,
          wobei amtliche Quellen Vorrang haben. Ein weiteres LLM ordnet die Treffer ein und gibt eine Bewertung ab
          (wie sehr wird die Aussage durch Daten gestützt), zusammen mit einer kurzen Begründung und den verwendeten
          Quellen. Das Ergebnis wird im Live-Transkript direkt an der betreffenden Textstelle markiert.
        </p>
        <p>
          Welcher Gast gerade spricht, erkennt die Transkription nur als „Sprecher A“, „Sprecher B“ usw. Die
          Zuordnung zu Namen nimmt ein Mensch per Klick vor – das System rät keine Namen, denn eine Aussage der
          falschen Person zuzuschreiben wäre schlimmer als gar keine Zuordnung.
        </p>
        <p>
          Der Schnellcheck ist bewusst auf Tempo ausgelegt: Er liefert eine Einordnung in Sekunden, keine
          erschöpfende Analyse. Für Details sei auf das{' '}
          <a href="https://github.com/mertensu/live_faktencheck">Github-Projekt</a> verwiesen.
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
