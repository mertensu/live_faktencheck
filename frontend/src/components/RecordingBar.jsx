import { MicSelect } from './MicSelect'

const BLOCK_OPTIONS = [60, 120, 180]

export function formatElapsed(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, '0')
  const s = String(totalSeconds % 60).padStart(2, '0')
  return `${m}:${s}`
}

// Presentational: the recorder state/controls are owned by FactCheckPage (so
// recording survives switching between the Review and Pro views) and passed in.
// `live` is the optional useAudioStream object for the streaming fast lane; when
// present, a "Live-Check" control is shown alongside the classic block recorder.
export function RecordingBar({ recorder, live }) {
  const {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds, start, sendNow, stop,
    remainingSeconds,
  } = recorder

  const isRecording = status === 'recording'
  const isRequesting = status === 'requesting'

  return (
    <div className="recording-bar">
      {isRecording ? (
        <>
          <span className="recording-bar-rec">● REC {formatElapsed(elapsed)}</span>
          <MicSelect recorder={recorder} className="recording-bar-mic" />
          <label className="recording-bar-interval">
            Blocklänge:
            <select value={blockSeconds} disabled>
              {BLOCK_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}s</option>
              ))}
            </select>
          </label>
          <span className="recording-bar-count">Blöcke gesendet: {blocksSent}</span>
          {remainingSeconds != null && (
            <span className="recording-bar-remaining">
              noch {formatElapsed(Math.max(remainingSeconds, 0))} übrig
            </span>
          )}
          <button className="recording-bar-send" onClick={() => sendNow()}>Senden</button>
          <button className="recording-bar-stop" onClick={() => stop()}>Stop</button>
        </>
      ) : (
        <>
          <MicSelect recorder={recorder} className="recording-bar-mic" disabled={isRequesting} />
          <label className="recording-bar-interval">
            Blocklänge:
            <select
              value={blockSeconds}
              onChange={(e) => setBlockSeconds(Number(e.target.value))}
              disabled={isRequesting}
            >
              {BLOCK_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}s</option>
              ))}
            </select>
          </label>
          <button
            className="recording-bar-start"
            onClick={() => start()}
            disabled={isRequesting}
          >
            {isRequesting ? 'Mikrofon…' : 'Aufnahme starten'}
          </button>
        </>
      )}
      {error && <span className="recording-bar-error">{error}</span>}
      {live && <LiveControls live={live} blockRecording={isRecording || isRequesting} />}
    </div>
  )
}

// Streaming fast-lane control. Kept separate from the block recorder; the two are
// mutually exclusive (both would grab the mic), so each disables the other while active.
function LiveControls({ live, blockRecording }) {
  const streaming = live.status === 'streaming'
  const connecting = live.status === 'connecting'
  const active = streaming || connecting

  return (
    <span className="recording-bar-live">
      {active ? (
        <>
          <span className="recording-bar-live-dot" aria-hidden="true">◉</span>
          {connecting ? 'Live verbindet…' : 'LIVE'}
          {live.partial && <span className="recording-bar-live-partial" title={live.partial}>{live.partial}</span>}
          <button className="recording-bar-stop" onClick={() => live.stop()}>Live stoppen</button>
        </>
      ) : (
        <button
          className="recording-bar-start"
          onClick={() => live.start()}
          disabled={blockRecording}
          title={blockRecording ? 'Erst die Blockaufnahme stoppen' : 'Live-Check starten (Streaming)'}
        >
          Live-Check starten
        </button>
      )}
      {live.error && <span className="recording-bar-error">{live.error}</span>}
    </span>
  )
}
