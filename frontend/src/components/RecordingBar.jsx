const BLOCK_OPTIONS = [60, 120, 180]

export function formatElapsed(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, '0')
  const s = String(totalSeconds % 60).padStart(2, '0')
  return `${m}:${s}`
}

// Presentational: the recorder state/controls are owned by FactCheckPage (so
// recording survives switching between the Review and Pro views) and passed in.
export function RecordingBar({ recorder }) {
  const {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds, start, sendNow, stop,
  } = recorder

  const isRecording = status === 'recording'
  const isRequesting = status === 'requesting'

  return (
    <div className="recording-bar">
      {isRecording ? (
        <>
          <span className="recording-bar-rec">● REC {formatElapsed(elapsed)}</span>
          <label className="recording-bar-interval">
            Blocklänge:
            <select value={blockSeconds} disabled>
              {BLOCK_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}s</option>
              ))}
            </select>
          </label>
          <span className="recording-bar-count">Blöcke gesendet: {blocksSent}</span>
          <button className="recording-bar-send" onClick={() => sendNow()}>Senden</button>
          <button className="recording-bar-stop" onClick={() => stop()}>Stop</button>
        </>
      ) : (
        <>
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
    </div>
  )
}
