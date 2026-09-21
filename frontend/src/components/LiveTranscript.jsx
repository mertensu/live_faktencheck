import { useEffect, useRef } from 'react'

// Verdict → short label + modifier class for the badge and the transcript highlight.
const VERDICT = {
  hoch: { label: 'hoch', mod: 'hoch' },
  niedrig: { label: 'niedrig', mod: 'niedrig' },
  unklar: { label: 'unklar', mod: 'unklar' },
  'keine Datenlage': { label: 'keine Datenlage', mod: 'keine' },
}

function verdictInfo(c) {
  if (c.status === 'processing') return { label: 'prüft…', mod: 'processing' }
  if (c.status === 'error') return { label: 'Fehler', mod: 'error' }
  return VERDICT[c.consistency] || { label: c.consistency || 'unklar', mod: 'unklar' }
}

// Split one transcript line into plain text + <mark> spans for every claim source
// sentence found in it. The mark is coloured by that claim's verdict so the moderator
// sees, in the flow of the transcript, exactly what was picked up and how it checked out.
function renderLine(text, claimsBySource) {
  const sources = Object.keys(claimsBySource).filter((s) => s && text.includes(s))
  if (sources.length === 0) return text

  // Earliest-match-first, non-overlapping.
  const hits = sources
    .map((s) => ({ s, i: text.indexOf(s) }))
    .sort((a, b) => a.i - b.i)

  const out = []
  let cursor = 0
  hits.forEach(({ s, i }, k) => {
    if (i < cursor) return // overlaps a previous mark; skip
    if (i > cursor) out.push(text.slice(cursor, i))
    const info = verdictInfo(claimsBySource[s])
    out.push(
      <mark key={`m${k}`} className={`live-transcript-mark verdict-${info.mod}`} title={`Claim: ${claimsBySource[s].claim}`}>
        {text.slice(i, i + s.length)}
      </mark>
    )
    cursor = i + s.length
  })
  if (cursor < text.length) out.push(text.slice(cursor))
  return out
}

// Live transcript panel for the streaming fast lane. Shows finalized turns from
// AssemblyAI plus the current interim line, highlights the passages that were gated as
// claims, and lists those claims with their verdict underneath. Auto-scrolls to newest.
export function LiveTranscript({ live }) {
  const { status, transcript = [], partial = '', claims = [] } = live || {}
  const endRef = useRef(null)

  const active = status === 'connecting' || status === 'streaming'
  const hasContent = transcript.length > 0 || partial || claims.length > 0

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [transcript, partial, claims])

  if (!active && !hasContent) return null

  // Latest claim wins per source sentence (a result overwrites its own processing entry).
  const claimsBySource = {}
  for (const c of claims) if (c.source) claimsBySource[c.source] = c

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
            {renderLine(t.text, claimsBySource)}
          </p>
        ))}
        {partial && <p className="live-transcript-line live-transcript-partial">{partial}</p>}
        {!hasContent && <p className="live-transcript-empty">Warte auf Ton…</p>}
        <div ref={endRef} />
      </div>

      {claims.length > 0 && (
        <div className="live-transcript-claims">
          <div className="live-transcript-claims-head">Erkannte Behauptungen ({claims.length})</div>
          {claims.map((c) => {
            const info = verdictInfo(c)
            return (
              <div key={c.id} className="live-claim">
                <span className={`live-claim-badge verdict-${info.mod}`}>{info.label}</span>
                <span className="live-claim-text">
                  {c.speaker && <span className="live-claim-speaker">{c.speaker}: </span>}
                  {c.claim}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
