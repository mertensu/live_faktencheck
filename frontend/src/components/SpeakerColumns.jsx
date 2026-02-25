import { ClaimCard } from './ClaimCard'

export function SpeakerColumns({ speakers, groupedBySpeaker, onSelect }) {
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
                  onSelect={onSelect}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
