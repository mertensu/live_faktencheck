import { MicSelect } from './MicSelect'
import { ShareLink } from './ShareLink'
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

// Operator's screen before going live: check the sound, see who is checked, start.
// The share link for viewers sits below. Going live from here; the header only stops.
// Sound comes from a mic, or (Chrome, Edge) digitally from another browser tab.
export function LiveStartPanel({
  sessionId, mic, tab, audioSource, onAudioSource, speakers, excludedSpeakers, onStart, connecting, error,
}) {
  const fromTab = TAB_AUDIO_SUPPORTED && audioSource === 'tab'
  const hasPermission = mic.devices.some((d) => d.label)
  const measuring = fromTab ? !!tab.stream : hasPermission
  const { level, hasSignal, verified } = useMicLevel(mic.deviceId, measuring, fromTab ? tab.stream : null)

  const lit = level === null ? 0 : Math.round(level * METER_BARS)
  const excluded = new Set((excludedSpeakers || []).map((s) => s.trim().toLowerCase()))

  let signalText = fromTab ? 'Tab mit der Sendung wählen' : 'Mikrofone laden, um den Ton zu prüfen'
  if (measuring) signalText = hasSignal ? 'Signal kommt an' : verified ? 'Ton geprüft' : 'Noch kein Ton'

  return (
    <div className="live-start">
      <section className="live-start-card" aria-label="Live-Check vorbereiten">
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

        {speakers.length > 0 && (
          <div className="live-start-step">
            <StepMark n={2} done />
            <div className="live-start-body">
              <h2>Personen</h2>
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
            </div>
          </div>
        )}

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

      <ShareLink sessionId={sessionId} />
    </div>
  )
}
