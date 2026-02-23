import { ClaimCard } from './ClaimCard'

export function SpeakerColumns({ speakers, groupedBySpeaker, expandedIds, onToggle }) {
  return (
    <div className="speakers-container">
      {speakers.map((speaker) => {
        const claims = groupedBySpeaker[speaker] || []
        const count = claims.length
        return (
          <div key={speaker} className="speaker-column">
            <div className="speaker-header">
              <h2>{speaker}</h2>
              <span className="claim-count">{count} Behauptung{count !== 1 ? 'en' : ''}</span>
            </div>
            <div className="speaker-claims">
              {claims.map((claim) => (
                <ClaimCard
                  key={claim.id}
                  claim={claim}
                  isExpanded={expandedIds.has(claim.id)}
                  onToggle={() => onToggle(claim.id)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
