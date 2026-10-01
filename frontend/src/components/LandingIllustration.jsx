// Landing-page sketch of the live view: speaker bubbles with marked claims and an open
// result card, styled like LiveTranscript. The words are real sentences, blurred so they
// read as text but can't be read; colours and the verdict label stay sharp. Decorative only.

const Blur = ({ children }) => <span className="li-blur">{children}</span>

export function LandingIllustration() {
  return (
    <div className="li" aria-hidden="true">
      <div className="li-head">
        <span className="li-dot">◉</span>Live-Transkript<span className="li-count">3 Behauptungen</span>
      </div>
      <div className="li-bubble li-spk-0">
        <div className="li-name"><Blur>Gitta Connemann</Blur></div>
        <p>
          <Blur>Wir müssen ehrlich sein, </Blur>
          <span className="li-mark li-hoch"><Blur>rund die Hälfte aller Wohnungen wird heute noch mit Gas beheizt</Blur></span>
          <Blur>, und das ändert sich nicht über Nacht.</Blur>
        </p>
      </div>
      <div className="li-bubble li-spk-1">
        <div className="li-name"><Blur>Katharina Dröge</Blur></div>
        <p>
          <Blur>Das ist doch Panikmache. </Blur>
          <span className="li-mark li-unklar"><Blur>Die Förderanträge sind zuletzt sogar wieder gestiegen</Blur></span>
          <Blur>, fragen Sie die Verbraucherzentralen.</Blur>
        </p>
      </div>
      <div className="li-bubble li-spk-0">
        <div className="li-name"><Blur>Gitta Connemann</Blur></div>
        <p>
          <span className="li-mark li-niedrig li-open"><Blur>Die Gaspreise haben sich seit 2021 verdreifacht</Blur></span>
          <Blur>, und das zahlen am Ende die Mieter.</Blur>
        </p>
      </div>
      <div className="li-pop">
        <div className="li-pop-head">
          <span className="live-claim-badge verdict-niedrig">Niedrig</span>
          <span className="li-pop-speaker"><Blur>Gitta Connemann</Blur></span>
        </div>
        <p className="li-pop-claim"><Blur>Die Gaspreise für Haushalte haben sich seit 2021 verdreifacht.</Blur></p>
        <p className="li-pop-reason">
          <Blur>Laut Statistischem Bundesamt lagen die Preise 2022 zeitweise etwa doppelt so hoch, inzwischen liegen sie deutlich darunter.</Blur>
        </p>
        <ul className="li-pop-sources">
          <li><Blur>destatis.de</Blur></li>
          <li><Blur>bundesnetzagentur.de</Blur></li>
        </ul>
      </div>
    </div>
  )
}
