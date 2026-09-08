import { useEffect, useMemo, useRef, useState } from 'react'
import { getConsistencyColor, formatBegruendung, stripDateAnnotation } from './ClaimCard'

// Live "Fokus-Stream": fact-checks as one chronological stream, newest on top in
// full focus, older ones fading/blurring downward. Tapping a card brings it into
// focus and expands its reasoning + sources inline. Two filter groups (speaker,
// trust level) narrow the stream. Checks still running (status 'processing')
// appear greyed at the top with a short "being checked" note.

// Trust-level wording, consistent with the rest of the app ("Vertrauenslevel").
const VERDICTS = [
  { key: 'hoch', label: 'Hoch' },
  { key: 'niedrig', label: 'Niedrig' },
  { key: 'unklar', label: 'Unklar' },
  { key: 'keine', label: 'Keine Datenlage' },
]
const VLABEL = Object.fromEntries(VERDICTS.map((v) => [v.key, v.label]))

// Map the German consistency word onto a stable verdict key.
const vKey = (consistency) => {
  const l = (consistency || '').toLowerCase()
  if (l === 'hoch') return 'hoch'
  if (l === 'niedrig') return 'niedrig'
  if (l === 'unklar') return 'unklar'
  return 'keine'
}

const hhmm = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
}

const lastName = (name) => (name || '').trim().split(/\s+/).slice(-1)[0] || name

export function FactCheckStream({ factChecks }) {
  const [openKey, setOpenKey] = useState(null)
  const [speakers, setSpeakers] = useState(() => new Set())
  const [verdicts, setVerdicts] = useState(() => new Set())
  const [filtersOpen, setFiltersOpen] = useState(false)
  const containerRef = useRef(null)
  const barRef = useRef(null)
  const reduce = useRef(false)

  useEffect(() => {
    reduce.current = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  // Newest first.
  const ordered = useMemo(
    () => [...(factChecks || [])].sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)),
    [factChecks]
  )

  // Speaker filter options in order of first appearance.
  const speakerNames = useMemo(() => {
    const seen = []
    ordered.forEach((fc) => {
      const s = (fc.sprecher || '').trim()
      if (s && !seen.includes(s)) seen.push(s)
    })
    return seen
  }, [ordered])

  const filtered = useMemo(() => ordered.filter((fc) => {
    const s = (fc.sprecher || '').trim()
    if (speakers.size && !speakers.has(s)) return false
    // A trust-level filter hides still-running / errored checks — they have no level yet.
    const noLevel = fc.status === 'processing' || fc.status === 'error'
    if (verdicts.size && (noLevel || !verdicts.has(vKey(fc.consistency)))) return false
    return true
  }), [ordered, speakers, verdicts])

  const keyOf = (fc, i) => (fc.id != null ? String(fc.id) : `i${i}`)

  const focalLine = () => (barRef.current ? barRef.current.getBoundingClientRect().bottom + 20 : 100)

  // Depth-of-field: the card near the focus line is sharp; those below fade and
  // blur with distance. Re-run on scroll/resize and whenever the list changes.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    const run = () => {
      const f = focalLine()
      root.querySelectorAll('.fcs-card').forEach((card) => {
        const passive = card.classList.contains('fcs-pending') || card.classList.contains('fcs-errored')
        const r = card.getBoundingClientRect()
        const dist = (r.top + r.height * 0.30) - f
        let blur = 0, op = 1
        if (dist > 0) { blur = Math.min(3.4, dist / 230); op = Math.max(0.5, 1 - dist / 1400) }
        if (card.classList.contains('fcs-open')) { blur = 0; op = 1 }
        card.style.filter = (reduce.current || blur < 0.15) ? '' : `blur(${blur.toFixed(2)}px)`
        card.style.opacity = op.toFixed(3)
        card.classList.toggle('fcs-focused', Math.abs(dist) < 90 && !reduce.current && !passive)
      })
    }
    run()
    const onScroll = () => window.requestAnimationFrame(run)
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [filtered, openKey])

  const toggleIn = (setter) => (val) => setter((prev) => {
    const next = new Set(prev)
    if (next.has(val)) next.delete(val); else next.add(val)
    return next
  })
  const toggleSpeaker = toggleIn(setSpeakers)
  const toggleVerdict = toggleIn(setVerdicts)
  const resetFilters = () => { setSpeakers(new Set()); setVerdicts(new Set()) }

  const onCardTap = (key, el) => {
    const willOpen = openKey !== key
    setOpenKey(willOpen ? key : null)
    if (willOpen && el) {
      const y = window.scrollY + el.getBoundingClientRect().top - focalLine()
      window.scrollTo({ top: Math.max(0, y), behavior: reduce.current ? 'auto' : 'smooth' })
    }
  }

  if (ordered.length === 0) {
    return <p className="fcs-empty">Noch keine Ergebnisse</p>
  }

  const activeCount = speakers.size + verdicts.size
  const filtersActive = activeCount > 0
  const total = ordered.length

  return (
    <div className="fcs" ref={containerRef}>
      <div className="fcs-bar" ref={barRef}>
        <div className="fcs-bar-row">
          <button
            type="button"
            className="fcs-filter-toggle"
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((o) => !o)}
          >
            <svg className="fcs-filter-icon" width="15" height="15" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />
            </svg>
            Filter
            {activeCount > 0 && <span className="fcs-filter-badge">{activeCount}</span>}
            <svg className="fcs-filter-chev" width="12" height="12" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
          <span className="fcs-spacer" />
          <span className="fcs-count">
            {filtersActive ? `${filtered.length} von ${total}` : `${total} Aussagen`}
          </span>
          {filtersActive && (
            <button type="button" className="fcs-reset" onClick={resetFilters}>Zurücksetzen</button>
          )}
        </div>

        {filtersOpen && (
          <div className="fcs-panel">
            {speakerNames.length > 1 && (
              <div className="fcs-group">
                <span className="fcs-flabel">Sprecher</span>
                {speakerNames.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="fcs-chip"
                    aria-pressed={speakers.has(name)}
                    onClick={() => toggleSpeaker(name)}
                  >
                    {lastName(name)}
                  </button>
                ))}
              </div>
            )}
            <div className="fcs-group">
              <span className="fcs-flabel">Vertrauen</span>
              {VERDICTS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={`fcs-chip fcs-chip-${key}`}
                  aria-pressed={verdicts.has(key)}
                  onClick={() => toggleVerdict(key)}
                >
                  <span className="fcs-dot" style={{ background: getConsistencyColor(key) }} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <p className="fcs-empty">Keine Aussagen für diese Auswahl.</p>
      ) : (
        <div className="fcs-stream">
          {filtered.map((fc, i) => {
            const key = keyOf(fc, i)

            if (fc.status === 'processing') {
              return (
                <article key={key} className="fcs-card fcs-pending">
                  <div className="fcs-top">
                    <span className="fcs-spinner" aria-hidden="true" />
                    {fc.sprecher && <span className="fcs-speaker">{fc.sprecher}</span>}
                    <span className="fcs-time">{hhmm(fc.timestamp)}</span>
                    <span className="fcs-spacer" />
                    <span className="fcs-badge">wird geprüft…</span>
                  </div>
                  <div className="fcs-claim">{stripDateAnnotation(fc.behauptung)}</div>
                </article>
              )
            }

            if (fc.status === 'error') {
              return (
                <article key={key} className="fcs-card fcs-errored">
                  <div className="fcs-top">
                    <span className="fcs-err-icon" aria-hidden="true">!</span>
                    {fc.sprecher && <span className="fcs-speaker">{fc.sprecher}</span>}
                    <span className="fcs-time">{hhmm(fc.timestamp)}</span>
                  </div>
                  <div className="fcs-claim">{stripDateAnnotation(fc.behauptung)}</div>
                  {fc.begruendung && <p className="fcs-err-msg">{fc.begruendung}</p>}
                </article>
              )
            }

            const vk = vKey(fc.consistency)
            const isOpen = openKey === key
            return (
              <article
                key={key}
                className={`fcs-card fcs-v-${vk}${isOpen ? ' fcs-open' : ''}`}
                tabIndex={0}
                role="button"
                aria-expanded={isOpen}
                onClick={(e) => { if (e.target.closest('a')) return; onCardTap(key, e.currentTarget) }}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onCardTap(key, e.currentTarget) } }}
              >
                <span className="fcs-stripe" style={{ background: getConsistencyColor(vk) }} />
                <div className="fcs-top">
                  <span className="fcs-dot" style={{ background: getConsistencyColor(vk) }} />
                  {fc.sprecher && <span className="fcs-speaker">{fc.sprecher}</span>}
                  <span className="fcs-time">{hhmm(fc.timestamp)}</span>
                  <span className="fcs-spacer" />
                  {fc.double_check && (
                    <span className="fcs-flag" title="Bewertung unter Vorbehalt" aria-label="Bewertung unter Vorbehalt">⚠</span>
                  )}
                  <span className={`fcs-vlabel fcs-vlabel-${vk}`}>{VLABEL[vk]}</span>
                </div>
                <div className="fcs-claim">{stripDateAnnotation(fc.behauptung)}</div>
                <div className="fcs-foot-row">
                  <span className="fcs-chev" aria-hidden="true">▶</span>
                  <span className="fcs-time">Tippen für Details</span>
                </div>
                <div className="fcs-detail">
                  <div>
                    <div className="fcs-detail-inner">
                      {fc.begruendung
                        ? <div className="fcs-reason">{formatBegruendung(fc.begruendung)}</div>
                        : <p className="fcs-reason">Keine Begründung verfügbar.</p>}
                      {fc.quellen && fc.quellen.length > 0 && (
                        <ul className="fcs-sources">
                          {fc.quellen.map((q, idx) => {
                            const url = typeof q === 'object' ? q.url : q
                            const title = typeof q === 'object' && q.title ? q.title : url
                            return (
                              <li key={idx}>
                                <a className="fcs-src" href={url} target="_blank" rel="noopener noreferrer">{title}</a>
                              </li>
                            )
                          })}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            )
          })}
          {filtered.length > 1 && <p className="fcs-peek">↓ älter — tippen fokussiert</p>}
        </div>
      )}
    </div>
  )
}
