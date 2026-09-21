import { useEffect, useRef } from 'react'

// Live transcript panel for the streaming fast lane. Shows finalized turns from
// AssemblyAI plus the current interim (not-yet-final) line, and auto-scrolls to the
// newest text. Renders nothing until a live session has produced something.
export function LiveTranscript({ live }) {
  const { status, transcript = [], partial = '' } = live || {}
  const endRef = useRef(null)

  const active = status === 'connecting' || status === 'streaming'
  const hasContent = transcript.length > 0 || partial

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [transcript, partial])

  if (!active && !hasContent) return null

  return (
    <div className="live-transcript" aria-live="polite">
      <div className="live-transcript-head">
        <span className="live-transcript-dot" aria-hidden="true">◉</span>
        {status === 'connecting' ? 'Live verbindet…' : 'Live-Transkript'}
      </div>
      <div className="live-transcript-body">
        {transcript.map((t, i) => (
          <p key={i} className="live-transcript-line">
            {t.speaker && <span className="live-transcript-speaker">{t.speaker}: </span>}
            {t.text}
          </p>
        ))}
        {partial && <p className="live-transcript-line live-transcript-partial">{partial}</p>}
        {!hasContent && <p className="live-transcript-empty">Warte auf Ton…</p>}
        <div ref={endRef} />
      </div>
    </div>
  )
}
