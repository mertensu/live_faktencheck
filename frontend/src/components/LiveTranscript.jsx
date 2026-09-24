import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { formatBegruendung } from './ClaimCard'

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

const SPEAKER_COLORS = 8 // .live-bubble.spk-0 … spk-7 in App.css

// A diarization label shows as "Sprecher A" until the operator assigns it to a guest.
// Lines without a label stay "Unklar" in a neutral bubble: no name is ever guessed.
function speakerTitle(label, speakerMap) {
  if (!label) return 'Unklar'
  return speakerMap[label] || `Sprecher ${label}`
}

// Consecutive lines of the same label form one bubble, like a chat.
function groupTurns(transcript, speakerMap) {
  const groups = []
  for (const t of transcript) {
    const label = t.label || null
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.lines.push(t.text)
    else groups.push({ label, name: label ? speakerMap[label] || null : null, lines: [t.text] })
  }
  for (const g of groups) g.title = speakerTitle(g.label, speakerMap)
  return groups
}

// The bubble's name as a button: pick the guest this label belongs to.
function SpeakerPicker({ label, title, current, speakers, onPick }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const pick = (name) => { onPick(label, name); setOpen(false) }
  return (
    <span className="live-speaker-picker" ref={ref}>
      <button
        type="button"
        className="live-bubble-name live-speaker-button"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Sprecher zuordnen"
        onClick={() => setOpen((o) => !o)}
      >
        {title} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="live-speaker-menu" role="menu" aria-label={`Sprecher ${label} zuordnen`}>
          {speakers.map((name) => (
            <li key={name}>
              <button type="button" role="menuitemradio" aria-checked={name === current} onClick={() => pick(name)}>
                {name}
              </button>
            </li>
          ))}
          {current && (
            <li className="live-speaker-menu-clear">
              <button type="button" role="menuitem" onClick={() => pick(null)}>Zuordnung entfernen</button>
            </li>
          )}
        </ul>
      )}
    </span>
  )
}

// Split one transcript line into plain text + marks for every claim source sentence
// found in it. The mark is tinted by that claim's verdict; hovering or clicking it opens
// the result. Every claim id that got a mark is added to `marked`.
function renderLine(text, claimsBySource, handlers, marked) {
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
    const claim = claimsBySource[s]
    marked.add(claim.id)
    out.push(
      <mark
        key={`m${k}`}
        className={`live-transcript-mark verdict-${verdictInfo(claim).mod}`}
        {...handlers(claim.id)}
      >
        {text.slice(i, i + s.length)}
      </mark>
    )
    cursor = i + s.length
  })
  if (cursor < text.length) out.push(text.slice(cursor))
  return out
}

function ClaimPopover({ claim, speaker, anchor, onEnter, onLeave }) {
  const ref = useRef(null)
  const [pos, setPos] = useState(null)

  // Fixed positioning so the card floats above the page; follow the
  // mark on scroll/resize and flip above it when there is more room there.
  useLayoutEffect(() => {
    const place = () => {
      const el = anchor()
      if (!el || !ref.current) return
      const r = el.getBoundingClientRect()
      const vw = window.innerWidth
      const vh = window.innerHeight
      const w = ref.current.offsetWidth
      const h = ref.current.offsetHeight
      const left = Math.max(8, Math.min(r.left, vw - w - 8))
      const below = vh - r.bottom
      const top = below >= h + 12 || below >= r.top ? r.bottom + 6 : Math.max(8, r.top - h - 6)
      setPos({ left, top })
    }
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [anchor, claim])

  const info = verdictInfo(claim)
  return (
    <div
      ref={ref}
      className="live-popover"
      role="dialog"
      aria-label="Prüfergebnis"
      style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden', left: 0, top: 0 }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <div className="live-popover-head">
        <span className={`live-claim-badge verdict-${info.mod}`}>{info.label}</span>
        {speaker && <span className="live-popover-speaker">{speaker}</span>}
      </div>
      <p className="live-popover-claim">{claim.claim}</p>
      {claim.status === 'processing' && <p className="live-popover-note">Wird geprüft…</p>}
      {claim.status === 'error' && <p className="live-popover-note">Schnellprüfung fehlgeschlagen.</p>}
      {claim.status === 'done' && (claim.begruendung
        ? <div className="live-popover-reason">{formatBegruendung(claim.begruendung)}</div>
        : <p className="live-popover-note">Keine Begründung verfügbar.</p>)}
      {claim.quellen?.length > 0 && (
        <ul className="live-popover-sources">
          {claim.quellen.map((q, idx) => {
            const url = typeof q === 'object' ? q.url : q
            const title = typeof q === 'object' && q.title ? q.title : url
            return (
              <li key={idx}>
                <a href={url} target="_blank" rel="noopener noreferrer">{title}</a>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// Live transcript for the streaming fast lane, laid out on the page itself (no panel).
// Finalized turns from AssemblyAI appear as chat bubbles, one colour per speaker, plus
// the current interim line. Passages gated as claims are marked by verdict; hover or
// click a mark to see the result. While streaming, a click on a bubble's name assigns
// that diarization label to one of the episode's `speakers`.
export function LiveTranscript({ live, speakers = [] }) {
  const { status, transcript = [], partial = '', claims = [], speakerMap = {}, assignSpeaker } = live || {}
  const rootRef = useRef(null)
  const endRef = useRef(null)
  const stickRef = useRef(true) // follow new lines only while the newest one is in view
  const colorsRef = useRef(new Map()) // speaker name → palette slot, sticky per session
  const closeTimer = useRef(null)
  const [open, setOpen] = useState(null) // { id, pinned }

  const active = status === 'connecting' || status === 'streaming'
  const hasContent = transcript.length > 0 || partial || claims.length > 0

  // The page is the window: keep the newest line in view, but only while the user hasn't
  // scrolled up to reread, and not while a result is being read.
  useEffect(() => {
    const onScroll = () => {
      const end = endRef.current
      if (end) stickRef.current = end.getBoundingClientRect().top <= window.innerHeight + 80
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (stickRef.current && !open) endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [transcript, partial, claims, open])

  const cancelClose = () => clearTimeout(closeTimer.current)
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = setTimeout(() => setOpen((o) => (o && !o.pinned ? null : o)), 180)
  }
  useEffect(() => cancelClose, [])

  // Close a pinned card on Escape or a click elsewhere.
  useEffect(() => {
    if (!open?.pinned) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(null) }
    const onDown = (e) => {
      if (!e.target.closest?.('.live-popover, .live-transcript-mark, .live-orphan')) setOpen(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open?.pinned])

  const markHandlers = (id) => ({
    'data-claim-id': id,
    tabIndex: 0,
    role: 'button',
    'aria-expanded': open?.id === id,
    onMouseEnter: () => { cancelClose(); setOpen((o) => (o?.pinned ? o : { id, pinned: false })) },
    onMouseLeave: scheduleClose,
    onFocus: () => setOpen((o) => (o?.pinned ? o : { id, pinned: false })),
    onBlur: scheduleClose,
    onClick: () => { cancelClose(); setOpen((o) => (o?.id === id && o.pinned ? null : { id, pinned: true })) },
    onKeyDown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        setOpen((o) => (o?.id === id && o.pinned ? null : { id, pinned: true }))
      }
    },
  })

  const openId = open?.id
  const anchor = useCallback(
    () => rootRef.current?.querySelector(`[data-claim-id="${openId}"]`),
    [openId]
  )

  if (!active && !hasContent) return null

  // Latest claim wins per source sentence (a result overwrites its own processing entry).
  const claimsBySource = {}
  for (const c of claims) if (c.source) claimsBySource[c.source] = c

  // Colour per speaker, sticky for the session. A label keeps its colour when it gets a
  // name (the name inherits it), so assigning doesn't repaint the conversation.
  const colorOf = (g) => {
    const m = colorsRef.current
    const labelKey = `label:${g.label}`
    const key = g.name || labelKey
    if (!m.has(key)) m.set(key, m.has(labelKey) ? m.get(labelKey) : m.size % SPEAKER_COLORS)
    return m.get(key)
  }

  const canAssign = status === 'streaming' && speakers.length > 0 && typeof assignSpeaker === 'function'
  const marked = new Set()
  const groups = groupTurns(transcript, speakerMap)
  const bubbles = groups.map((g, gi) => (
    <div key={gi} className={`live-bubble ${g.label ? `spk-${colorOf(g)}` : 'spk-none'}`}>
      {canAssign && g.label
        ? <SpeakerPicker label={g.label} title={g.title} current={g.name} speakers={speakers} onPick={assignSpeaker} />
        : <div className="live-bubble-name">{g.title}</div>}
      {g.lines.map((line, li) => (
        <p key={li} className="live-bubble-line">{renderLine(line, claimsBySource, markHandlers, marked)}</p>
      ))}
    </div>
  ))
  // Claims can be found before the turn ends (early sentences), so mark the interim line too.
  const partialBubble = partial && (
    <div className="live-bubble live-bubble-partial">
      <p className="live-bubble-line">{renderLine(partial, claimsBySource, markHandlers, marked)}</p>
    </div>
  )
  // A claim whose sentence isn't (or no longer) visible verbatim still needs a way in.
  const orphans = Object.values(claimsBySource).filter((c) => !marked.has(c.id))
  const openClaim = claims.find((c) => c.id === openId)

  return (
    <div className="live-transcript" aria-live="polite" ref={rootRef}>
      <div className="live-transcript-head">
        <span className="live-transcript-dot" aria-hidden="true">◉</span>
        {status === 'connecting' ? 'Live verbindet…' : 'Live-Transkript'}
        {claims.length > 0 && (
          <span className="live-transcript-count">{Object.keys(claimsBySource).length} Behauptungen</span>
        )}
      </div>
      <div className="live-transcript-body">
        {bubbles}
        {partialBubble}
        {!hasContent && <p className="live-transcript-empty">Warte auf Ton…</p>}
      </div>

      {orphans.length > 0 && (
        <div className="live-orphans">
          <span className="live-orphans-head">Ohne Textstelle:</span>
          {orphans.map((c) => {
            const info = verdictInfo(c)
            return (
              <span key={c.id} className={`live-orphan live-claim-badge verdict-${info.mod}`} {...markHandlers(c.id)}>
                {info.label}
              </span>
            )
          })}
        </div>
      )}

      <div ref={endRef} />

      {openClaim && (
        <ClaimPopover
          claim={openClaim}
          speaker={openClaim.label ? speakerTitle(openClaim.label, speakerMap) : openClaim.speaker}
          anchor={anchor}
          onEnter={cancelClose}
          onLeave={scheduleClose}
        />
      )}
    </div>
  )
}
