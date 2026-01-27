export function AboutPage() {
  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Uber live-faktencheck.de</h1>
        <p>
          Live-Faktenchecks waren in der Vergangenheit immer wieder Diskussions-Thema. Mit der stetigen Entwicklung bestehender
          KI-Modelle sind wir nun, wie ich finde, an einem Punkt angelangt, der ein solches Projekt realisierbar macht. Dieses Projekt ist mein Versuch,
          einen Live-Faktencheck auf Basis von kunstlicher Intelligenz umzusetzen. Das Projekt ist bei Weitem nicht ausgereift und Fehler sind nicht ausgeschlossen.
          Nichtsdestotrotz hoffe ich, dass es fur den einen oder anderen interessant sein konnte und eine Hilfestellung darstellt.
          <br />
          Ich mochte betonen, dass es hier ausdrucklich nicht darum geht, die Gaste bzw. Content-Creator an den Pranger zu stellen, zu diskreditieren oder in sonstiger Weise
          in Verruf zu bringen. Es geht vielmehr darum, aufzuzeigen, wie sehr bestimmte Behauptungen durch Studien, Statistiken oder andere vertrauenswurdige Quellen, gestutzt werden.
          Somit bleiben die Aussagen nicht undiskutiert im Raume stehen, sondern werden einer (ersten) kritischen Betrachtung unterzogen, und zwar wahrend die Sendung lauft.
        </p>
        <h2>Wie es funktioniert</h2>
        <p>
          Die Sendungen werden in zeitlich begrenzte Blocke aufgeteilt und dann live transkribiert. Diese Transkripte werden an ein grosses Sprachmodell (LLM) weitergereicht,
          welches uberprufbare Behauptungen extrahiert und diese automatisch den jeweiligen Sprechern zuweist. Diese Aussagen werden dann auf Relevanz und Korrektheit gepruft und schliesslich
          einem weiteren Agenten (LLM) zur Bewertung ubergeben. Das Modell startet daraufhin eine Web-Recherche, wobei es sich auf
          vertrauenswurdige Seiten beschrankt (offizielle Regierungsseiten, anerkannte Institute, etc.). Das Modell nimmt eine Bewertung vor (wie sehr wird die Aussage durch Daten gestutzt),
          gibt eine ausfuhrliche Erklarung ab sowie die der Entscheidung zugrundliegenden Quellen an. Fur Details sei auf das <a href="https://github.com/mertensu/live_faktencheck">Github-Repository</a> verwiesen.
        </p>
        <h2>Hinweis</h2>
        <p>
          Die hier dargestellten Fakten-Checks werden automatisch mit Hilfe von
          Kunstlicher Intelligenz (KI) generiert. Die Inhalte konnen Fehler enthalten
          und sollten nicht als alleinige Grundlage fur Entscheidungen verwendet werden.
        </p>
      </div>
    </div>
  )
}
