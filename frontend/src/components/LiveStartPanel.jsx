import { useState } from 'react'
import { MicSelect } from './MicSelect'
import { ShareLink } from './ShareLink'
import { LivePractice } from './LiveTutorial'
import { useMicLevel } from '../hooks/useMicLevel'
import { TAB_AUDIO_SUPPORTED } from '../hooks/useTabAudio'

const METER_BARS = 10

function CheckIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function StepMark({ n, done }) {
  return (
    <span className={`live-start-mark${done ? ' live-start-mark--done' : ''}`}>
      {done ? <CheckIcon /> : n}
    </span>
  )
}

// Operator's screen before going live: an optional practice on made-up data (folded),
// then check the sound, see who is checked, start.
// Then the viewers' link (ticked once copied). Going live from here; the header only stops.
// Sound comes from a mic, or (Chrome, Edge) digitally from another browser tab.
export function LiveStartPanel({
  sessionId, mic, tab, audioSource, onAudioSource, speakers, excludedSpeakers, onStart, connecting, error,
  practiceOpen, onPracticeOpen,
}) {
  const fromTab = TAB_AUDIO_SUPPORTED && audioSource === 'tab'
  const hasPermission = mic.devices.some((d) => d.label)
  const measuring = fromTab ? !!tab.stream : hasPermission
  const { level, hasSignal, verified } = useMicLevel(mic.deviceId, measuring, fromTab ? tab.stream : null)

  const [linkCopied, setLinkCopied] = useState(false)
  // "Fertig" sits at the bottom of the practice: folding it would leave the view below
  // the card's top, so bring the practice's own row back into view.
  const closePractice = () => {
    onPracticeOpen(false)
    requestAnimationFrame(() =>
      document.getElementById('live-practice')?.scrollIntoView?.({ block: 'nearest' }))
  }

  const lit = level === null ? 0 : Math.round(level * METER_BARS)
  const excluded = new Set((excludedSpeakers || []).map((s) => s.trim().toLowerCase()))

  let signalText = fromTab ? 'Tab mit der Sendung wählen' : 'Mikrofone laden, um den Ton zu prüfen'
  if (measuring) signalText = hasSignal ? 'Signal kommt an' : verified ? 'Ton geprüft' : 'Noch kein Ton'

  return (
    <div className="live-start">
      <section className="live-start-card" aria-label="Live-Check vorbereiten">
        <div className={`live-start-practice${practiceOpen ? ' live-start-practice--open' : ''}`} id="live-practice">
          <button
            type="button"
            className="live-start-practice-head"
            aria-expanded={practiceOpen}
            onClick={() => onPracticeOpen(!practiceOpen)}
          >
            <span className="live-start-mark live-start-mark--practice" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 4 20 12 6 20 6 4" /></svg>
            </span>
            <span className="live-start-practice-title">
              <strong>Bedienung üben</strong>
              <span>Optional · 2 Minuten · mit Beispieldaten, nichts wird veröffentlicht</span>
            </span>
            <svg className="live-start-chevron" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9" /></svg>
          </button>
          {practiceOpen && (
            <div className="live-start-practice-body">
              <LivePractice onDone={closePractice} />
            </div>
          )}
        </div>

        <div className="live-start-step">
          <StepMark n={1} done={verified} />
          <div className="live-start-body">
            <div className="live-start-row">
              <h2>Ton prüfen</h2>
              <span className={`live-start-signal${verified ? ' live-start-signal--ok' : ''}`} role="status">
                {signalText}
              </span>
            </div>
            {TAB_AUDIO_SUPPORTED && (
              <div className="live-start-source" role="radiogroup" aria-label="Tonquelle">
                {[['mic', 'Mikrofon'], ['tab', 'Browser-Tab']].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={audioSource === value}
                    className={audioSource === value ? 'active' : ''}
                    onClick={() => onAudioSource(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {fromTab ? (
              <div className="live-start-tab">
                <button type="button" className="mic-select-load" onClick={tab.pick}>
                  {tab.stream ? 'Anderen Tab wählen' : 'Tab auswählen'}
                </button>
                {tab.stream && <span className="live-start-tab-ok">Tab-Ton verbunden</span>}
              </div>
            ) : (
              <MicSelect mic={mic} className="live-start-mic" />
            )}
            {measuring && (
              <div className="live-start-meter" aria-hidden="true">
                {Array.from({ length: METER_BARS }, (_, i) => (
                  <span key={i} className={i < lit ? 'on' : ''} style={{ height: `${8 + ((i * 7) % 5) * 4}px` }} />
                ))}
              </div>
            )}
            {fromTab && tab.error && <p className="live-start-error" role="alert">{tab.error}</p>}
            {fromTab ? (
              <p className="live-start-hint">
                Den Tab mit der Sendung offen lassen und beim Teilen „Tab-Audio teilen“ anhaken.
                Sie hören den Ton weiter. Lautstärke über das System regeln, den Tab nicht stummschalten.
              </p>
            ) : (
              <p className="live-start-hint">
                Spielen Sie die Sendung auf einem anderen Gerät ab als dem, das aufnimmt –
                viele Geräte filtern den eigenen Ton heraus.
                {TAB_AUDIO_SUPPORTED && ' Läuft die Sendung hier im Browser, wählen Sie „Browser-Tab“.'}
              </p>
            )}
          </div>
        </div>

        <div className="live-start-step">
          <StepMark n={2} done={speakers.length > 0} />
          <div className="live-start-body">
            <h2>Personen</h2>
            {speakers.length > 0 ? (
              <ul className="live-start-people">
                {speakers.map((name) => {
                  const skip = excluded.has(name.trim().toLowerCase())
                  return (
                    <li key={name} className={skip ? '' : 'checked'}>
                      {name} · {skip ? 'nicht geprüft' : 'wird geprüft'}
                    </li>
                  )
                })}
              </ul>
            ) : (
              // Without names the backend publishes every voice's claims (no hold).
              <p className="live-start-hint">
                Keine Personen angegeben. Die Stimmen erscheinen im Transkript als Sprecher A, B, C,
                und die Aussagen aller Stimmen werden geprüft, auch die der Moderation.
              </p>
            )}
          </div>
        </div>

        <div className="live-start-step">
          <StepMark n={3} done={linkCopied} />
          <div className="live-start-body">
            <h2>Link für Zuschauer</h2>
            <ShareLink sessionId={sessionId} onCopied={() => setLinkCopied(true)} />
          </div>
        </div>

        <div className="live-start-go">
          <button type="button" className="live-start-button" onClick={onStart} disabled={connecting}>
            <span className="live-start-dot" aria-hidden="true" />
            {connecting ? 'Verbinde…' : 'Live-Check starten'}
          </button>
          {error
            ? <p className="live-start-error" role="alert">{error}</p>
            : <p className="live-start-note">Startet Transkript und Prüfung. Stoppen jederzeit oben rechts.</p>}
        </div>
      </section>
    </div>
  )
}

// Touch only, no mouse or trackpad (a phone, a tablet without one). Assigning speakers and
// marking passages need a pointer, so the live check is not started there; a laptop with a
// touch screen or an iPad with a trackpad has a fine pointer and is fine.
export function isTouchOnly() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(pointer: coarse)').matches && !window.matchMedia('(any-pointer: fine)').matches
}

// In place of the start panel on a touch-only device: just where to go instead.
export function LiveStartDesktopOnly() {
  return (
    <div className="live-start">
      <p className="live-start-card live-start-desktop" role="note">
        Am Smartphone lassen sich Sprecher nicht zuverlässig zuordnen und korrigieren. Öffnen Sie
        diesen Faktencheck bitte an einem Laptop oder PC, um fortzufahren.
      </p>
    </div>
  )
}
