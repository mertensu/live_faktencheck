import { useEffect, useRef, useState } from 'react'

// Animated explainer of the live pipeline for the About page. One example sentence travels
// through all steps. Each scene is plain HTML whose parts fade in via CSS animation delays
// (--d); the base styles are the final state, so with animations off every scene is complete.
// The clock is the progress bar of the active step: its animationend advances the scene, so
// pausing (button, scrolled out of view) is just animation-play-state.

const STEPS = [
  {
    title: 'Zuhören',
    text: 'Der Ton der Sendung wird live transkribiert und erscheint Satz für Satz. Die Transkription unterscheidet nur „Sprecher A“, „Sprecher B“ – Namen ordnet ein Mensch per Klick zu.',
    ms: 4500,
  },
  {
    title: 'Auswählen',
    text: 'Ein schnelles KI-Modell schätzt für jeden Satz ein, ob er eine überprüfbare und relevante Tatsachenbehauptung enthält. Liegt ein Satz im Graubereich, holt es eine zweite Meinung ein.',
    ms: 7000,
  },
  {
    title: 'Umformulieren',
    text: 'Ein Sprachmodell macht aus dem Satz eine eigenständige Aussage – mit Blick auf die vorigen Sätze, damit etwa „da“ aufgelöst wird – und leitet Suchanfragen aus fünf Blickwinkeln ab.',
    ms: 6000,
  },
  {
    title: 'Recherchieren',
    text: 'Die Suchen laufen parallel und nur auf vertrauenswürdigen Seiten: Statistikämter, Ministerien, Forschungsinstitute. Amtliche Quellen haben Vorrang.',
    ms: 4500,
  },
  {
    title: 'Bewerten',
    text: 'Ein weiteres Sprachmodell wägt die Treffer ab: Wie stark stützen die Daten die Aussage? Erwähnen Treffer nur ein Dokument, wird es bei Bedarf gesucht und nachgelesen.',
    ms: 6000,
  },
  {
    title: 'Markieren',
    text: 'Nach wenigen Sekunden steht das Ergebnis direkt an der Textstelle im Live-Transkript – mit Begründung und den verwendeten Quellen.',
    ms: 6500,
  },
]

const d = (s) => ({ '--d': `${s}s` })

const WAVE = [40, 75, 55, 90, 35, 70, 95, 50, 80, 45, 65, 85, 30, 60, 90, 50]

function SceneListen() {
  return (
    <div className="pa-scene">
      <div className="pa-live">
        <span className="pa-live-dot" />Live-Ton
        <span className="pa-wave" aria-hidden="true">
          {WAVE.map((h, i) => <i key={i} style={{ height: `${h}%`, '--i': i }} />)}
        </span>
      </div>
      <div className="pa-bubble pa-spk-0 pa-in" style={d(0.3)}>
        <div className="pa-name">Sprecher A</div>
        <p>
          <span className="pa-fade" style={d(0.3)}>Nehmen wir die Wärmewende. </span>
          <span className="pa-fade" style={d(1.4)}>Da wird rund die Hälfte aller Wohnungen noch mit Gas beheizt.</span>
        </p>
      </div>
      <div className="pa-bubble pa-spk-1 pa-in" style={d(2.6)}>
        <div className="pa-name">Sprecher B</div>
        <p>Die Leute haben schlicht Angst vor den Kosten.</p>
      </div>
    </div>
  )
}

const GATE_ROWS = [
  { text: 'Nehmen wir die Wärmewende.', p: 0.06, out: 'skip' },
  { text: 'Da wird rund die Hälfte aller Wohnungen noch mit Gas beheizt.', p: 0.93, out: 'check' },
  { text: 'Die Leute haben schlicht Angst vor den Kosten.', p: 0.55, out: 'grey' },
]

function SceneGate() {
  return (
    <div className="pa-scene">
      <div className="pa-gate-row pa-gate-head" aria-hidden="true">
        <span />
        <span className="pa-gate-legend"><span>überspringen</span><span>Graubereich</span><span>prüfen</span></span>
      </div>
      {GATE_ROWS.map((r, i) => {
        const t = 0.3 + i * 1.2
        return (
          <div key={r.text} className={`pa-gate-row pa-in${r.out === 'check' ? ' pa-gate-row--hit' : ''}`} style={d(t)}>
            <p className="pa-gate-text">{r.text}</p>
            <div className="pa-meter" aria-hidden="true">
              <div className="pa-meter-fill" style={{ ...d(t + 0.2), width: `${r.p * 100}%` }} />
            </div>
            <div className="pa-gate-out">
              {r.out === 'skip' && <span className="pa-chip pa-chip--skip pa-in" style={d(t + 1)}>übersprungen</span>}
              {r.out === 'check' && <span className="pa-chip pa-chip--check pa-in" style={d(t + 1)}>prüfen ✓</span>}
              {r.out === 'grey' && (
                <>
                  <span className="pa-chip pa-chip--pending" style={d(t + 1)}>zweite Meinung …</span>
                  <span className="pa-chip pa-chip--skip pa-in" style={d(t + 2.3)}>zweite Meinung: nein</span>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const QUERIES = [
  { angle: 'Kern', q: 'Anteil Wohnungen mit Gasheizung Deutschland', hit: 'destatis.de' },
  { angle: 'Datenquelle', q: 'Destatis Wohnungen nach Beheizungsart', hit: 'destatis.de' },
  { angle: 'Studie', q: 'Studie Heizungsarten im Wohnungsbestand', hit: 'umweltbundesamt.de' },
  { angle: 'Maßstab', q: 'Wohnungen nach überwiegender Heizenergie', hit: 'bdh-industrie.de' },
  { angle: 'Einordnung', q: 'Entwicklung Anteil Gasheizungen seit 2010', hit: 'bundesregierung.de' },
]

function SceneRewrite() {
  return (
    <div className="pa-scene">
      <p className="pa-orig pa-in" style={d(0.2)}>
        „<span className="pa-ref">Da</span> wird rund die Hälfte aller Wohnungen noch mit Gas beheizt.“
        <span className="pa-ctx">vorher: „Nehmen wir die Wärmewende.“</span>
      </p>
      <div className="pa-down pa-in" style={d(0.9)} aria-hidden="true">↓</div>
      <p className="pa-claim pa-in" style={d(1.2)}>
        <span className="pa-ref pa-ref--new">In Deutschland</span> wird rund die Hälfte aller Wohnungen mit Gas beheizt.
      </p>
      <ul className="pa-queries">
        {QUERIES.map((x, i) => (
          <li key={x.angle} className="pa-in" style={d(2.2 + i * 0.35)}>
            <span className="pa-angle">{x.angle}</span><span className="pa-q">{x.q}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SceneSearch() {
  return (
    <div className="pa-scene">
      <div className="pa-filter pa-in" style={d(0.1)}>🔒 nur vertrauenswürdige Quellen · amtliche zuerst</div>
      <ul className="pa-lanes">
        {QUERIES.map((x, i) => (
          <li key={x.angle} className="pa-lane">
            <span className="pa-angle">{x.angle}</span>
            <span className="pa-track" aria-hidden="true">
              <span className="pa-track-fill" style={{ ...d(0.5), '--dur': `${1.3 + (i % 3) * 0.35}s` }} />
            </span>
            <span className="pa-hit pa-in" style={d(1.9 + (i % 3) * 0.35)}>{x.hit}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const LEVELS = [
  { key: 'hoch', label: 'Hoch' },
  { key: 'niedrig', label: 'Niedrig' },
  { key: 'unklar', label: 'Unklar' },
  { key: 'keine', label: 'Keine Datenlage' },
]

function SceneJudge() {
  return (
    <div className="pa-scene pa-judge">
      <ul className="pa-evidence">
        <li className="pa-in" style={d(0.2)}><b>destatis.de</b> Wohnungen nach Heizenergie</li>
        <li className="pa-in" style={d(0.5)}><b>umweltbundesamt.de</b> Wärmeversorgung im Bestand</li>
        <li className="pa-doc pa-in" style={d(2.4)}>
          <span className="pa-doc-tag">erwähnt → nachgelesen</span>
          <b>Bericht (PDF)</b> Beheizungsstruktur
        </li>
      </ul>
      <div className="pa-verdict">
        <div className="pa-levels">
          {LEVELS.map((l, i) => (
            <span
              key={l.key}
              className={`live-claim-badge verdict-${l.key} pa-level${l.key === 'hoch' ? ' pa-level--on' : ''}`}
              style={d(1 + i * 0.3)}
            >
              {l.label}
            </span>
          ))}
        </div>
        <p className="pa-reason pa-in" style={d(3.2)}>
          Amtliche Daten zeigen: Knapp jede zweite Wohnung wird überwiegend mit Gas beheizt.
        </p>
      </div>
    </div>
  )
}

function SceneMark() {
  return (
    <div className="pa-scene">
      <div className="pa-bubble pa-spk-0">
        <div className="pa-name">Sprecher A</div>
        <p>
          Nehmen wir die Wärmewende.{' '}
          <span className="li-mark li-hoch pa-mark" style={d(0.6)}>
            Da wird rund die Hälfte aller Wohnungen noch mit Gas beheizt.
          </span>
        </p>
      </div>
      <div className="li-pop pa-pop pa-in" style={d(1.8)}>
        <div className="li-pop-head">
          <span className="live-claim-badge verdict-hoch">Hoch</span>
          <span className="li-pop-speaker">Sprecher A</span>
        </div>
        <p className="li-pop-claim">In Deutschland wird rund die Hälfte aller Wohnungen mit Gas beheizt.</p>
        <p className="li-pop-reason">Amtliche Daten zeigen: Knapp jede zweite Wohnung wird überwiegend mit Gas beheizt.</p>
        <ul className="li-pop-sources"><li>destatis.de</li><li>umweltbundesamt.de</li></ul>
      </div>
    </div>
  )
}

const SCENES = [SceneListen, SceneGate, SceneRewrite, SceneSearch, SceneJudge, SceneMark]

export function PipelineAnimation() {
  const [step, setStep] = useState(0)
  // Bumped on every (re)start of a step, so the scene and its progress bar remount.
  const [run, setRun] = useState(0)
  const [paused, setPaused] = useState(false)
  const [inView, setInView] = useState(false)
  const [reduced, setReduced] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    setReduced(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.35 })
    io.observe(rootRef.current)
    return () => io.disconnect()
  }, [])

  const goTo = (i) => {
    setStep(i)
    setRun((r) => r + 1)
  }

  const advance = (e) => {
    if (e.target !== e.currentTarget) return
    goTo((step + 1) % STEPS.length)
  }

  const running = inView && !paused && !reduced
  const Scene = SCENES[step]
  const cur = STEPS[step]

  return (
    <section
      ref={rootRef}
      className={`pa${running ? '' : ' pa--halted'}${reduced ? ' pa--still' : ''}`}
      aria-label="Ablauf eines Faktenchecks"
    >
      <ol className="pa-rail">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <button
              type="button"
              className={`pa-step${i === step ? ' pa-step--on' : ''}${i < step ? ' pa-step--done' : ''}`}
              aria-current={i === step ? 'step' : undefined}
              onClick={() => goTo(i)}
            >
              <span className="pa-step-num">{i + 1}</span>
              <span className="pa-step-title">{s.title}</span>
              <span className="pa-step-bar" aria-hidden="true">
                {i === step && !reduced && (
                  <span
                    key={run}
                    className="pa-step-fill"
                    data-testid="pa-clock"
                    style={{ animationDuration: `${s.ms}ms` }}
                    onAnimationEnd={advance}
                  />
                )}
              </span>
            </button>
          </li>
        ))}
      </ol>

      <div className="pa-main">
        <div className="pa-stage">
          <span className="pa-example">Beispiel, vereinfacht</span>
          <Scene key={run} />
        </div>
        <div className="pa-caption">
          <p>
            <strong>{step + 1} · {cur.title}.</strong> {cur.text}
          </p>
          {!reduced && (
            <button type="button" className="pa-toggle" onClick={() => setPaused((p) => !p)}>
              {paused ? '▶ Abspielen' : '❚❚ Pause'}
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
