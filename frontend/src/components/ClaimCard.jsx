import React from 'react'
import { createPortal } from 'react-dom'

// Strip date annotations like "(Stand März 2026)" or "(im März 2026)" from claim text
export const stripDateAnnotation = (text) => {
  if (!text) return text
  return text.replace(/\s*\((Stand|im)\s+\w+\s+\d{4}\)/g, '')
}

// Markdown regex patterns - compiled once at module load for better performance
const MARKDOWN_BOLD_PATTERN = /\*\*(.+?)\*\*/g
const MARKDOWN_ITALIC_PATTERN = /(?<!\*)\*([^*]+?)\*(?!\*)/g
const MARKDOWN_LINK_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g

export const getConsistencyColor = (consistency) => {
  const lower = consistency?.toLowerCase() || ''
  if (lower === 'hoch') return '#22c55e'
  if (lower === 'niedrig') return '#ef4444'
  if (lower === 'unklar') return '#f59e0b'
  return '#6b7280' // keine Datenlage or unknown
}

export const getConsistencyClass = (consistency) => {
  const lower = consistency?.toLowerCase() || ''
  if (lower === 'hoch') return 'verdict-richtig'
  if (lower === 'niedrig') return 'verdict-falsch'
  if (lower === 'unklar') return 'verdict-unklar'
  return 'verdict-unbelegt' // keine Datenlage or unknown
}

// Simple Markdown formatting (bold, italic, links)
const formatMarkdown = (text) => {
  if (!text) return text

  let match
  const matches = []

  // Reset lastIndex for global regex patterns (they maintain state)
  MARKDOWN_BOLD_PATTERN.lastIndex = 0
  MARKDOWN_ITALIC_PATTERN.lastIndex = 0
  MARKDOWN_LINK_PATTERN.lastIndex = 0

  // Pattern for **bold**
  while ((match = MARKDOWN_BOLD_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'bold',
      start: match.index,
      end: match.index + match[0].length,
      content: match[1]
    })
  }

  // Pattern for *italic*
  while ((match = MARKDOWN_ITALIC_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'italic',
      start: match.index,
      end: match.index + match[0].length,
      content: match[1]
    })
  }

  // Pattern for [text](url)
  while ((match = MARKDOWN_LINK_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'link',
      start: match.index,
      end: match.index + match[0].length,
      text: match[1],
      url: match[2]
    })
  }

  // Sort matches by position
  matches.sort((a, b) => a.start - b.start)

  // Build React elements
  if (matches.length === 0) {
    return text
  }

  const elements = []
  let currentIndex = 0

  matches.forEach((match, idx) => {
    // Text before the match
    if (match.start > currentIndex) {
      elements.push(text.substring(currentIndex, match.start))
    }

    // The match itself
    if (match.type === 'bold') {
      elements.push(<strong key={`bold-${idx}`}>{match.content}</strong>)
    } else if (match.type === 'italic') {
      elements.push(<em key={`italic-${idx}`}>{match.content}</em>)
    } else if (match.type === 'link') {
      elements.push(
        <a key={`link-${idx}`} href={match.url} target="_blank" rel="noopener noreferrer" className="begruendung-link">
          {match.text}
        </a>
      )
    }

    currentIndex = match.end
  })

  // Rest of the text
  if (currentIndex < text.length) {
    elements.push(text.substring(currentIndex))
  }

  return elements.length > 0 ? <>{elements}</> : text
}

// Format reasoning: line breaks and simple Markdown
export const formatBegruendung = (text) => {
  if (!text) return null

  // Replace \n\n with paragraphs
  const paragraphs = text.split(/\n\n+/).filter(p => p.trim())

  return paragraphs.map((para, idx) => {
    // A paragraph that is only **…** is a heading (agent check: "Was die Quellen sagen").
    const heading = para.trim().match(/^\*\*([^*\n]+)\*\*$/)
    if (heading) return <h3 key={idx} className="begruendung-heading">{heading[1]}</h3>
    // Replace single \n with <br>
    const lines = para.split('\n')
    return (
      <p key={idx} className="begruendung-text">
        {lines.map((line, lineIdx) => (
          <React.Fragment key={lineIdx}>
            {lineIdx > 0 && <br />}
            {formatMarkdown(line)}
          </React.Fragment>
        ))}
      </p>
    )
  })
}

export function ClaimCard({ claim, onSelect }) {
  if (claim.status === 'processing') {
    return (
      <div
        className="claim-card claim-card--processing"
        data-tooltip="Recherche läuft, bitte noch ein wenig Geduld"
      >
        <div className="claim-header">
          <div className="claim-text">
            <span className="claim-processing-spinner" aria-hidden="true" />
            {stripDateAnnotation(claim.behauptung)}
          </div>
        </div>
      </div>
    )
  }

  if (claim.status === 'error') {
    return (
      <div className="claim-card claim-card--error">
        <div className="claim-header">
          <div className="claim-text">
            <span className="claim-error-icon" aria-hidden="true">!</span>
            {stripDateAnnotation(claim.behauptung)}
          </div>
        </div>
        {claim.begruendung && (
          <div className="claim-error-message">{claim.begruendung}</div>
        )}
      </div>
    )
  }

  const consistencyClass = getConsistencyClass(claim.consistency)

  return (
    <div
      className={`claim-card ${consistencyClass} claim-card--clickable`}
      onClick={() => onSelect(claim)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(claim) }}
    >
      <div className="claim-header">
        <div className="claim-text">{stripDateAnnotation(claim.behauptung)}</div>
        <div className="claim-header-actions">
          {claim.check_depth === 'fast' && (
            <span className="fast-check-flag" aria-label="Schnellcheck" title="Schnellcheck – automatische Bewertung in Sekunden">Schnellcheck</span>
          )}
          {claim.double_check && (
            <span className="double-check-flag" aria-label="Bewertung unter Vorbehalt" title="Bewertung unter Vorbehalt">⚠</span>
          )}
          <span className="expand-button" aria-hidden="true">▶</span>
        </div>
      </div>
    </div>
  )
}

// Reasoning of a result in a card or popover: the short version when the check wrote one
// (agent check), else the long one. The long one then opens in ClaimDetailPanel.
export function Begruendung({ kurz, lang, className }) {
  return <div className={className}>{formatBegruendung(kurz || lang)}</div>
}

// Top-right button that opens the full result. Stops the click: stream cards open and
// close on a tap.
// Trash icon: hide the check ("Verwerfen"). Kept apart from ExpandButton (bottom left vs.
// top right) so the two are hard to mix up.
export function DiscardButton({ onClick }) {
  const discard = (e) => { e.stopPropagation(); onClick() }
  return (
    <button
      type="button"
      className="claim-discard"
      title="Check verwerfen"
      aria-label="Check verwerfen"
      onClick={discard}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
        <path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.5M9.2 6.5v4.5"
          fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}

export function ExpandButton({ onClick }) {
  const open = (e) => { e.stopPropagation(); onClick() }
  return (
    <button
      type="button"
      className="claim-expand"
      title="Mehr anzeigen"
      aria-label="Mehr anzeigen"
      onClick={open}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
        <path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9"
          fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}

// The whole result at a glance: slides in from the right (full screen on a phone), so the
// long reasoning needs no scrolling inside a small popover or card.
// detail: { speaker, claim, consistency, label, kurz, begruendung, quellen }
const CLOSE_MS = 220 // .claim-detail-*--closing in App.css
export function ClaimDetailPanel({ detail, onClose }) {
  const [closing, setClosing] = React.useState(false)
  const onCloseRef = React.useRef(onClose)
  onCloseRef.current = onClose
  const timer = React.useRef(null)

  // Unmount on a timer, not on animationend: a missed event (an animation that does not
  // run) would leave an invisible backdrop over the page.
  const close = React.useCallback(() => {
    if (timer.current) return
    setClosing(true)
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    timer.current = setTimeout(() => onCloseRef.current(), reduce ? 0 : CLOSE_MS)
  }, [])

  React.useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
      clearTimeout(timer.current)
    }
  }, [close])

  return createPortal(
    <div className={`claim-detail-backdrop${closing ? ' claim-detail-backdrop--closing' : ''}`} onClick={close}>
      <div
        className={`claim-detail-panel${closing ? ' claim-detail-panel--closing' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Prüfergebnis"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button type="button" className="claim-detail-close" onClick={close}>← Zurück</button>
        <div className="claim-detail-body">
          <div className="claim-detail-meta">
            <span className="claim-detail-verdict" style={{ background: getConsistencyColor(detail.consistency) }}>
              {detail.label}
            </span>
            {detail.speaker && <span className="claim-detail-speaker">{detail.speaker}</span>}
          </div>
          <h2 className="claim-detail-heading">{stripDateAnnotation(detail.claim)}</h2>
          {detail.kurz && <p className="claim-detail-lead">{detail.kurz}</p>}
          <div className="claim-detail-reason">{formatBegruendung(detail.begruendung)}</div>
          {detail.quellen?.length > 0 && (
            <>
              <h3 className="claim-detail-section-title">Quellen</h3>
              <ul className="claim-detail-sources">
                {detail.quellen.map((q, idx) => {
                  const url = typeof q === 'object' ? q.url : q
                  const title = typeof q === 'object' && q.title ? q.title : url
                  return <li key={idx}><a href={url} target="_blank" rel="noopener noreferrer">{title}</a></li>
                })}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
