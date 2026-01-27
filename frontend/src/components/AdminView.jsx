export function AdminView({ pendingClaims, stagedClaims, sentClaims, onStage, onUnstage, onUpdatePending, onSendAll, onResend }) {
  return (
    <div className="admin-layout">
      {/* Top row: 2 columns side by side */}
      <div className="admin-top-row">
        {/* Left: Pending Claims List */}
        <div className="admin-panel admin-pending">
          <div className="admin-panel-header">
            <h2>Pending Claims</h2>
            <span className="panel-count">{pendingClaims.length}</span>
          </div>
          {pendingClaims.length === 0 ? (
            <div className="admin-panel-empty">
              <p>Keine Claims zur Bearbeitung</p>
              <p className="empty-subtitle">Warte auf neue Claims...</p>
            </div>
          ) : (
            <div className="admin-claims-list">
              {pendingClaims.map((claim) => (
                <div key={claim.id} className="admin-claim-item pending-item">
                  <div className="claim-content">
                    <input
                      type="text"
                      className="claim-speaker-edit"
                      value={claim.name}
                      onChange={(e) => onUpdatePending(claim.id, 'name', e.target.value)}
                      placeholder="Sprecher"
                    />
                    <textarea
                      className="claim-text-edit"
                      value={claim.claim}
                      onChange={(e) => onUpdatePending(claim.id, 'claim', e.target.value)}
                      placeholder="Claim"
                      rows={3}
                    />
                    <div className="claim-meta">
                      {new Date(claim.timestamp).toLocaleString('de-DE')}
                    </div>
                  </div>
                  <button
                    className="stage-button"
                    onClick={() => onStage(claim.id)}
                    title="Zum Staging hinzufugen"
                  >
                    {'\u2192'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Staging Area */}
        <div className="admin-panel admin-staging">
          <div className="admin-panel-header">
            <h2>Staging Area</h2>
            <span className="panel-count">{stagedClaims.length}</span>
          </div>
          {stagedClaims.length === 0 ? (
            <div className="admin-panel-empty">
              <p>Keine Claims bereit zum Senden</p>
              <p className="empty-subtitle">Klicke {'\u2192'} bei einem Claim</p>
            </div>
          ) : (
            <>
              <div className="admin-claims-list">
                {stagedClaims.map((claim) => (
                  <div key={claim.id} className="admin-claim-item staged-item">
                    <button
                      className="unstage-button"
                      onClick={() => onUnstage(claim.id)}
                      title="Zuruck zum Bearbeiten"
                    >
                      {'\u2190'}
                    </button>
                    <div className="claim-content readonly">
                      <div className="claim-speaker-display">{claim.name || 'Unbekannt'}</div>
                      <div className="claim-text-display">{claim.claim}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="staging-actions">
                <button
                  className="action-button primary send-all-button"
                  onClick={onSendAll}
                >
                  Alle {stagedClaims.length} Claims senden
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Bottom row: Sent Claims History */}
      <div className="admin-bottom-row">
        <div className="admin-panel admin-sent">
          <div className="admin-panel-header">
            <h2>Gesendete Claims</h2>
            <span className="panel-count">{sentClaims.length}</span>
          </div>
          {sentClaims.length === 0 ? (
            <div className="admin-panel-empty compact">
              <p>Noch keine Claims gesendet</p>
            </div>
          ) : (
            <div className="sent-claims-list">
              {sentClaims.map((claim) => (
                <div key={claim.id} className="sent-claim-item">
                  <div className="sent-claim-content">
                    <span className="sent-speaker">{claim.name || 'Unbekannt'}</span>
                    <span className="sent-text">{claim.claim}</span>
                    <span className="sent-timestamp">
                      {new Date(claim.sentAt).toLocaleString('de-DE')}
                    </span>
                  </div>
                  <button
                    className="resend-button"
                    onClick={() => onResend(claim.id)}
                    title="Erneut senden (kopiert zu Pending)"
                  >
                    Re-send
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
