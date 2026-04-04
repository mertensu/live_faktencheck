import { useState, useEffect } from 'react'
import { ClaimCard } from './ClaimCard'

export function SpeakerColumns({ speakers, groupedBySpeaker, onSelect }) {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 767px)').matches)
  const [collapsed, setCollapsed] = useState({})

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const handler = (e) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const toggle = (speaker) =>
    setCollapsed(prev => ({ ...prev, [speaker]: !prev[speaker] }))

  return (
    <div className="speakers-container">
      {speakers.map((speaker) => {
        const claims = groupedBySpeaker[speaker] || []
        const count = claims.length
        const hoch = claims.filter(c => c.consistency?.toLowerCase() === 'hoch').length
        const niedrig = claims.filter(c => c.consistency?.toLowerCase() === 'niedrig').length
        const scorable = hoch + niedrig
        const score = scorable > 0 ? Math.round(hoch / scorable * 100) : null
        const isCollapsed = isMobile && !!collapsed[speaker]
        return (
          <div key={speaker} className="speaker-column">
            <div
              className={`speaker-header${isMobile ? ' speaker-header--toggle' : ''}`}
              onClick={isMobile ? () => toggle(speaker) : undefined}
            >
              <div className="speaker-header-top">
                <h2>{speaker}</h2>
                {score !== null && (() => {
                  const unklar = claims.filter(c => c.consistency?.toLowerCase() === 'unklar').length
                  const keineDate = claims.filter(c => c.consistency?.toLowerCase() === 'keine datenlage').length
                  const excluded = unklar + keineDate
                  const tooltipParts = [
                    `${hoch} Behauptung${hoch !== 1 ? 'en' : ''} korrekt, ${niedrig} falsch`,
                    excluded > 0 ? `${excluded} nicht gewertet (unklar oder keine Datenlage)` : null,
                    `${hoch}/${scorable} = ${score}%`
                  ].filter(Boolean).join(' · ')
                  return (
                    <span className="credibility-score">
                      Credibility-Score: {score}
                      <span className="credibility-info" aria-label="Wie wird der Score berechnet?">
                        ⓘ
                        <span className="credibility-tooltip">{tooltipParts}</span>
                      </span>
                    </span>
                  )
                })()}
              </div>
              <div className="speaker-header-bottom">
                <span className="claim-count">{count} Behauptung{count !== 1 ? 'en' : ''}</span>
                {isMobile && (
                  <span className={`speaker-toggle-chevron${isCollapsed ? ' speaker-toggle-chevron--collapsed' : ''}`}>
                    ▾
                  </span>
                )}
              </div>
            </div>
            {!isCollapsed && (
              <div className="speaker-claims">
                {claims.map((claim) => (
                  <ClaimCard
                    key={claim.id}
                    claim={claim}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
