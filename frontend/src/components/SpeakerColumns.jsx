import { ClaimCard } from './ClaimCard'

export function SpeakerColumns({ speakers, groupedBySpeaker, expandedIds, onToggle }) {
  return (
    <>
      {/* Speaker Headers - side by side */}
      <div className="speakers-container">
        {speakers.map((speaker) => {
          const count = groupedBySpeaker[speaker]?.length || 0
          return (
            <div key={speaker} className="speaker-column">
              <div className="speaker-header">
                <h2>{speaker}</h2>
                <span className="claim-count">{count} Behauptung{count !== 1 ? 'en' : ''}</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Claims under speakers */}
      <div className="claims-container">
        {speakers.map((speaker) => {
          const claims = groupedBySpeaker[speaker] || []
          return (
            <div key={speaker} className="speaker-claims-column">
              {claims.length === 0 ? (
                <div className="no-claims">Noch keine Behauptungen</div>
              ) : (
                claims.map((claim) => (
                  <ClaimCard
                    key={claim.id}
                    claim={claim}
                    isExpanded={expandedIds.has(claim.id)}
                    onToggle={() => onToggle(claim.id)}
                  />
                ))
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}
