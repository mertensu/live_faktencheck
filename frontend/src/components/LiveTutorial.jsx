import { useCallback, useEffect, useRef, useState } from 'react'
import { LiveTranscript } from './LiveTranscript'
import { assignFrom, nameAt, splitPassages } from '../hooks/useAudioStream'

// Made-up guests for the practice transcript; never the episode's real ones.
const HOST = 'Anna Keller'
const GUEST_B = 'Peter Müller'
const GUEST_C = 'Sandra Berger'
const SPEAKERS = [HOST, GUEST_B, GUEST_C]

const line = (label, turnOrder, text) => ({ label, turnOrder, text })

const SCENES = {
  names: {
    transcript: [
      line('A', 0, 'Guten Abend und herzlich willkommen. Heute sprechen wir über die Rente.'),
      line('B', 1, 'Danke für die Einladung. Das Thema beschäftigt sehr viele Menschen.'),
      line('A', 2, 'Herr Müller, fangen wir gleich bei Ihnen an.'),
      line('B', 3, 'Gern. Die Lage ist ernster, als viele glauben.'),
    ],
  },
  passage: {
    // Diarization folded Sandra's voice into the host's label A.
    transcript: [
      line('A', 0, 'Frau Berger, wie sehen Sie das?'),
      line('A', 1, 'Ganz anders. Die Beiträge sind seit Jahren stabil geblieben.'),
      line('B', 2, 'Das stimmt so einfach nicht.'),
      line('A', 3, 'Doch, das zeigen die Zahlen der letzten zehn Jahre.'),
    ],
    speakerMap: { A: [[-1, HOST]], B: [[-1, GUEST_B]] },
  },
  results: {
    transcript: [
      line('A', 0, 'Herr Müller, wie viele Menschen beziehen denn heute Rente?'),
      line('B', 1, 'In Deutschland beziehen rund 21 Millionen Menschen eine Rente. Und die Renten sind seit 2010 real gesunken.'),
      line('C', 2, 'Das halte ich für falsch, die Renten sind gestiegen.'),
    ],
    speakerMap: { A: [[-1, HOST]], B: [[-1, GUEST_B]], C: [[-1, GUEST_C]] },
    claims: [
      {
        id: 'tut-1', speaker: GUEST_B, label: 'B', status: 'done', consistency: 'hoch',
        claim: 'In Deutschland beziehen rund 21 Millionen Menschen eine Rente.',
        source: 'In Deutschland beziehen rund 21 Millionen Menschen eine Rente.',
        begruendung: 'Übungsbeispiel: Die Zahl passt zur Größenordnung der amtlichen Statistik. Im echten Check stehen hier Begründung und Quellen.',
      },
      {
        id: 'tut-2', speaker: GUEST_B, label: 'B', status: 'done', consistency: 'niedrig',
        claim: 'Die Renten sind seit 2010 real gesunken.',
        source: 'Und die Renten sind seit 2010 real gesunken.',
        begruendung: 'Übungsbeispiel: Die Belege sprechen gegen die Aussage. Im echten Check stehen hier Begründung und Quellen.',
      },
    ],
  },
}

// A stand-in for useAudioStream's live object: same shape, but the operator's assignments
// only change local state, with the same timeline and passage logic as the real session.
function usePracticeLive(scene) {
  const [transcript, setTranscript] = useState(scene.transcript)
  const [speakerMap, setSpeakerMap] = useState(scene.speakerMap || {})
  const assignSpeaker = useCallback((label, name, fromTurn = null) => {
    setSpeakerMap((m) => assignFrom(m, label, fromTurn, name || null))
  }, [])
  const assignPassage = useCallback((parts, name) => {
    if (name) setTranscript((t) => splitPassages(t, parts, name))
  }, [])
  return {
    status: 'streaming', partial: '', transcript, claims: scene.claims || [], speakerMap,
    assignSpeaker, assignPassage,
  }
}

function Done({ children }) {
  return <p className="live-tutorial-done" role="status">✓ {children}</p>
}

// A step reports once its task is done (the tab gets its tick).
function useSolved(solved, onSolved) {
  useEffect(() => { if (solved) onSolved?.() }, [solved, onSolved])
}

function NamesStep({ onSolved }) {
  const live = usePracticeLive(SCENES.names)
  const named = Object.keys(live.speakerMap).length > 0
  useSolved(named, onSolved)
  return (
    <>
      <p>
        Das System hört nur, dass <em>verschiedene</em> Stimmen sprechen, und nennt sie
        Sprecher A, B, … <strong>Ihre Aufgabe</strong> ist es daher, jede Stimme einmal der
        richtigen Person zuzuordnen, sobald sie zum ersten Mal spricht. Stimmen aus einem Einspieler ordnen
        Sie <em>Andere Stimme – nicht prüfen</em> zu.
      </p>
      <p className="live-tutorial-task">
        Probieren Sie es aus: Klicken Sie oben in einer Sprechblase auf <strong>Sprecher A ▾</strong> und wählen Sie {HOST}.
      </p>
      <LiveTranscript live={live} speakers={SPEAKERS} follow={false} />
      {named && (
        <Done>
          Die Zuordnung gilt ab dieser Sprechblase für alles, was diese Stimme danach sagt.
          Frühere Sprechblasen behalten ihren Namen.
        </Done>
      )}
    </>
  )
}

// Correction in two parts: 1 with "auch alles Weitere" (the default), 2 without it.
function PassageStep({ onSolved, follow }) {
  const [round, setRound] = useState(0)
  return <PassagePractice key={round} follow={follow} onReset={() => setRound((r) => r + 1)} onSolved={onSolved} />
}

function PassagePractice({ follow, onReset, onSolved }) {
  const live = usePracticeLive(SCENES.passage)
  const assigned = live.transcript.some((t) => t.speaker)
  const followed = nameAt(live.speakerMap, 'A', 3) === GUEST_C
  const right = assigned && followed === follow
  useSolved(right, onSolved)
  return (
    <>
      {follow ? (
        <p>
          Das System ist nicht perfekt, und so kann es besonders in den ersten Minuten einer
          Aufnahme vorkommen, dass ähnliche Stimmen unter einem Sprecher landen. Hier steckt {GUEST_C} mit
          in der Sprechblase von {HOST}, und zwar nicht nur einmal.
        </p>
      ) : (
        <p>
          Dieselbe Stelle, aber diesmal ein einzelner Ausrutscher: Nur diese eine Antwort von {GUEST_C} ist
          bei {HOST} gelandet, danach stimmt die Zuordnung wieder.
        </p>
      )}
      <p className="live-tutorial-task">
        Markieren Sie mit der Maus ihre Antwort „Ganz anders. … stabil geblieben.“, {follow
          ? <>lassen Sie <em>auch alles Weitere von Sprecher A</em> angehakt</>
          : <>entfernen Sie den Haken bei <em>auch alles Weitere von Sprecher A</em></>} und wählen Sie im Menü {GUEST_C}.
      </p>
      <LiveTranscript live={live} speakers={SPEAKERS} follow={false} />
      {assigned && (
        <div className={right ? 'live-tutorial-done' : 'live-tutorial-retry'} role="status">
          {followed ? (
            <p>
              {right ? '✓ ' : ''}<strong>„auch alles Weitere“ aktiviert:</strong> Auch die spätere Zeile von Sprecher A wird jetzt {GUEST_C} zugeordnet.
              Richtig, wenn die zwei Stimmen weiter vermischt sind. Spricht später wieder {HOST},
              klicken Sie in ihrer Sprechblase auf den Namen ({GUEST_C} ▾) und wählen Sie {HOST}. Ab dieser
              Sprechblase stimmt der Name dann wieder.
            </p>
          ) : (
            <p>
              {right ? '✓ ' : ''}<strong>„auch alles Weitere“ deaktiviert:</strong> Nur die markierte Stelle wurde von {GUEST_C} gesprochen; die spätere
              Zeile bleibt bei {HOST}. Richtig für einen einzelnen Ausrutscher.
            </p>
          )}
          {!right && (
            <button type="button" className="live-tutorial-reset" onClick={onReset}>
              Zurücksetzen und noch einmal versuchen
            </button>
          )}
        </div>
      )}
    </>
  )
}

function ResultsStep({ onSolved }) {
  const live = usePracticeLive(SCENES.results)
  const [opened, setOpened] = useState(false)
  useSolved(opened, onSolved)
  const onClickCapture = (e) => {
    if (e.target.closest?.('.live-transcript-mark')) setOpened(true)
  }
  return (
    <>
      <p>
        Farbig markierte Stellen sind geprüfte Behauptungen: <span className="live-tutorial-chip verdict-hoch">grün</span> passt zu den Belegen,{' '}
        <span className="live-tutorial-chip verdict-niedrig">rot</span> widerspricht ihnen,{' '}
        <span className="live-tutorial-chip verdict-unklar">orange</span> unklar.
      </p>
      <p className="live-tutorial-task">Klicken Sie auf eine Markierung, um Begründung und Quellen zu sehen.</p>
      <div onClickCapture={onClickCapture}>
        <LiveTranscript live={live} speakers={SPEAKERS} follow={false} />
      </div>
      {opened && <Done>So öffnen Sie im Live-Check jedes Ergebnis.</Done>}
      <p className="live-tutorial-tip">
        Sie können nun den Live-Faktencheck starten.
      </p>
    </>
  )
}

const STEPS = [
  { title: 'Namen vergeben', Body: NamesStep },
  { title: 'Korrektur 1', Body: (p) => <PassageStep {...p} follow /> },
  { title: 'Korrektur 2', Body: (p) => <PassageStep {...p} follow={false} /> },
  { title: 'Ergebnisse lesen', Body: ResultsStep },
]

// The practice: four steps on the real LiveTranscript with made-up data, as tabs with a
// "Weiter" button. Inline in the start panel before going live; onDone after the last step.
export function LivePractice({ onDone }) {
  const [step, setStep] = useState(0)
  const [solved, setSolved] = useState([])
  const { Body } = STEPS[step]
  const last = step === STEPS.length - 1
  const solve = useCallback(() => setSolved((s) => (s.includes(step) ? s : [...s, step])), [step])
  // "Weiter" sits below the step: on a small screen the next step would start out of view.
  const topRef = useRef(null)
  const next = () => {
    setStep(step + 1)
    // Up to the tabs if they left the view ('nearest' stops short on a step taller than it).
    requestAnimationFrame(() => {
      const el = topRef.current
      if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView?.({ block: 'start' })
    })
  }

  return (
    <div className="live-practice" ref={topRef}>
      <div className="live-practice-tabs" role="tablist" aria-label="Übungsschritte">
        {STEPS.map((s, i) => (
          <button
            key={s.title}
            type="button"
            role="tab"
            aria-selected={i === step}
            className={i === step ? 'active' : ''}
            onClick={() => setStep(i)}
          >
            <span className={`live-practice-mark${solved.includes(i) ? ' live-practice-mark--done' : ''}`}>
              {solved.includes(i) ? '✓' : i + 1}
            </span>
            <span>{s.title}</span>
          </button>
        ))}
      </div>
      <div className="live-tutorial-body" role="tabpanel">
        <Body key={step} onSolved={solve} />
      </div>
      <div className="live-practice-foot">
        <span>Schritt {step + 1} von {STEPS.length}</span>
        <button type="button" className="live-practice-next" onClick={() => (last ? onDone() : next())}>
          {last ? 'Fertig – Übung schließen' : `Weiter: ${STEPS[step + 1].title}`}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// The same practice in a dialog: "Kurzanleitung" while a session is live or has results,
// when the start panel (and its inline practice) is gone. Skippable, also with Escape.
export function LiveTutorial({ onClose }) {
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    // Escape closes an open speaker menu or result first; only a bare Escape skips the guide.
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      if (document.querySelector('.live-tutorial .live-speaker-menu, .live-popover')) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return (
    <div className="live-tutorial-overlay">
      <div className="live-tutorial" role="dialog" aria-modal="true" aria-labelledby="live-tutorial-title">
        <div className="live-tutorial-head">
          <h2 id="live-tutorial-title">Kurzanleitung Live-Check</h2>
          <button type="button" className="live-tutorial-skip" onClick={onClose}>Schließen</button>
        </div>
        <LivePractice onDone={onClose} />
      </div>
    </div>
  )
}
