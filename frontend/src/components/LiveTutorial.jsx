import { useCallback, useEffect, useState } from 'react'
import { LiveTranscript } from './LiveTranscript'
import { assignFrom, nameAt, splitPassages } from '../hooks/useAudioStream'

// Made-up guests for the practice transcript; never the episode's real ones.
const HOST = 'Anna Beispiel'
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

function NamesStep() {
  const live = usePracticeLive(SCENES.names)
  const named = Object.keys(live.speakerMap).length > 0
  return (
    <>
      <p>
        Das System hört nur, dass <em>verschiedene</em> Stimmen sprechen, und nennt sie
        Sprecher A, B, … <strong>Wer das ist, sagst du.</strong> Es rät nie einen Namen.
      </p>
      <p className="live-tutorial-task">
        Probier es: Klick oben in einer Blase auf <strong>Sprecher A ▾</strong> und wähle {HOST}.
      </p>
      <LiveTranscript live={live} speakers={SPEAKERS} />
      {named && (
        <Done>
          Die Zuordnung gilt ab dieser Blase für alles, was diese Stimme danach sagt.
          Frühere Blasen behalten ihren Namen.
        </Done>
      )}
    </>
  )
}

function PassageStep() {
  const [round, setRound] = useState(0)
  return <PassagePractice key={round} onReset={() => setRound((r) => r + 1)} />
}

function PassagePractice({ onReset }) {
  const live = usePracticeLive(SCENES.passage)
  const assigned = live.transcript.some((t) => t.speaker)
  const followed = nameAt(live.speakerMap, 'A', 3) === GUEST_C
  return (
    <>
      <p>
        Ähnliche Stimmen landen manchmal unter einem Buchstaben. Hier steckt {GUEST_C} mit in
        der Blase von {HOST}.
      </p>
      <p className="live-tutorial-task">
        Markiere mit der Maus ihre Antwort „Ganz anders. … stabil geblieben.“ und wähle im Menü {GUEST_C}. Achte auf
        den Haken <em>auch alles Weitere von Sprecher A</em>.
      </p>
      <LiveTranscript live={live} speakers={SPEAKERS} />
      {assigned && (
        <div className="live-tutorial-done" role="status">
          {followed ? (
            <p>
              ✓ <strong>Haken an:</strong> Auch die spätere Zeile von Sprecher A heißt jetzt {GUEST_C}.
              Richtig, wenn die zwei Stimmen weiter vermischt sind. Spricht {HOST} danach wieder,
              klick dort auf den Blasennamen und stell es ab da zurück.
            </p>
          ) : (
            <p>
              ✓ <strong>Haken aus:</strong> Nur die markierte Stelle heißt {GUEST_C}; die spätere
              Zeile bleibt bei {HOST}. Richtig für einen einzelnen Ausrutscher.
            </p>
          )}
          <button type="button" className="live-tutorial-reset" onClick={onReset}>
            Zurücksetzen und mit Haken {followed ? 'aus' : 'an'} probieren
          </button>
        </div>
      )}
    </>
  )
}

function ResultsStep() {
  const live = usePracticeLive(SCENES.results)
  const [opened, setOpened] = useState(false)
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
      <p className="live-tutorial-task">Klick auf eine Markierung, um Begründung und Quellen zu sehen.</p>
      <div onClickCapture={onClickCapture}>
        <LiveTranscript live={live} speakers={SPEAKERS} />
      </div>
      {opened && <Done>So öffnest du im Live-Check jedes Ergebnis.</Done>}
      <p className="live-tutorial-tip">
        <strong>Starte den Live-Check zu Sendungsbeginn und bleib die ersten Minuten dran.</strong>{' '}
        Dann sprechen alle zum ersten Mal – wer jetzt früh zuordnet, hat die Namen für den Rest der Sendung.
      </p>
    </>
  )
}

const STEPS = [
  { title: 'Namen vergibst du', Body: NamesStep },
  { title: 'Vermischte Stimmen trennen', Body: PassageStep },
  { title: 'Ergebnisse lesen', Body: ResultsStep },
]

// Short interactive guide to the live check, on the real LiveTranscript with made-up data.
// Shown every time an operator opens a session page; skippable, and reopenable from the header.
export function LiveTutorial({ onClose }) {
  const [step, setStep] = useState(0)
  const { title, Body } = STEPS[step]
  const last = step === STEPS.length - 1

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
          <span className="live-tutorial-kicker">Kurzanleitung Live-Check · {step + 1} von {STEPS.length}</span>
          <button type="button" className="live-tutorial-skip" onClick={onClose}>Überspringen</button>
        </div>
        <h2 id="live-tutorial-title">{title}</h2>
        <div className="live-tutorial-body">
          <Body key={step} />
        </div>
        <div className="live-tutorial-foot">
          <div className="live-tutorial-dots" aria-hidden="true">
            {STEPS.map((s, i) => <span key={s.title} className={i === step ? 'is-active' : ''} />)}
          </div>
          {step > 0 && (
            <button type="button" className="action-button" onClick={() => setStep(step - 1)}>Zurück</button>
          )}
          <button
            type="button"
            className="action-button primary"
            onClick={() => (last ? onClose() : setStep(step + 1))}
          >
            {last ? 'Los geht’s' : 'Weiter'}
          </button>
        </div>
      </div>
    </div>
  )
}
