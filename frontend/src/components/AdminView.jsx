import { useState } from 'react'

export function AdminView({ pendingClaims, pendingBlocks, stagedClaims, discardedClaims, sentClaims, onStage, onUnstage, onDiscard, onUndiscard, onDiscardCollection, onUpdatePending, onSendAll, onResend }) {
  const [expandedBlocks, setExpandedBlocks] = useState(new Set())

  const toggleBlock = (blockId) => {
    setExpandedBlocks(prev => {
      const next = new Set(prev)
      if (next.has(blockId)) {
        next.delete(blockId)
      } else {
        next.add(blockId)
      }
      return next
    })
  }

  // Resend claims are shown as standalone items at the top
  const resendClaims = pendingClaims.filter(c => c.resendOf)
  const totalPendingCount = pendingClaims.length

  return (
    <div className="admin-layout">
      {/* Top row: 2 columns side by side */}
      <div className="admin-top-row">
        {/* Left: Pending Claims List */}
        <div className="admin-panel admin-pending">
          <div className="admin-panel-header">
            <h2>Pending Claims</h2>
            <span className="panel-count">{totalPendingCount}</span>
          </div>
          {totalPendingCount === 0 ? (
            <div className="admin-panel-empty">
              <p>Keine Claims zur Bearbeitung</p>
              <p className="empty-subtitle">Warte auf neue Claims...</p>
            </div>
          ) : (
            <div className="admin-claims-list">
              {/* Resend claims as standalone items */}
              {resendClaims.map((claim) => (
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
                      Re-send &middot; {new Date(claim.timestamp).toLocaleString('de-DE')}
                    </div>
                  </div>
                  <div className="claim-actions">
                    <button
                      className="stage-button"
                      onClick={() => onStage(claim.id)}
                      title="Zum Staging hinzufugen"
                    >
                      {'\u2192'}
                    </button>
                    <button
                      className="discard-button"
                      onClick={() => onDiscard(claim.id)}
                      title="Verwerfen"
                    >
                      {'\u2715'}
                    </button>
                  </div>
                </div>
              ))}

              {/* Block collections */}
              {(pendingBlocks || []).map((block) => (
                <div key={block.blockId} className="claim-collection">
                  <div className="collection-header">
                    <button
                      className="collection-toggle"
                      onClick={() => toggleBlock(block.blockId)}
                      title={expandedBlocks.has(block.blockId) ? 'Einklappen' : 'Ausklappen'}
                    >
                      {expandedBlocks.has(block.blockId) ? '\u25BC' : '\u25B6'}
                    </button>
                    <div className="collection-info">
                      <span className="collection-timestamp">
                        {new Date(block.timestamp).toLocaleString('de-DE')}
                      </span>
                      {block.info && (
                        <span className="collection-block-info">{block.info}</span>
                      )}
                      <span className="collection-count">{block.claims.length} Claims</span>
                    </div>
                    <button
                      className="discard-all-button"
                      onClick={() => onDiscardCollection(block.blockId)}
                      title="Alle Claims dieses Blocks verwerfen"
                    >
                      Alle verwerfen
                    </button>
                  </div>
                  {expandedBlocks.has(block.blockId) && (
                    <div className="collection-claims">
                      {block.claims.map((claim) => (
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
                          <div className="claim-actions">
                            <button
                              className="stage-button"
                              onClick={() => onStage(claim.id)}
                              title="Zum Staging hinzufugen"
                            >
                              {'\u2192'}
                            </button>
                            <button
                              className="discard-button"
                              onClick={() => onDiscard(claim.id)}
                              title="Verwerfen"
                            >
                              {'\u2715'}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
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

      {/* Discarded Claims */}
      <div className="admin-bottom-row">
        <div className="admin-panel admin-discarded">
          <div className="admin-panel-header">
            <h2>Verworfen</h2>
            <span className="panel-count">{discardedClaims.length}</span>
          </div>
          {discardedClaims.length === 0 ? (
            <div className="admin-panel-empty compact">
              <p>Keine verworfenen Claims</p>
            </div>
          ) : (
            <div className="discarded-claims-list">
              {discardedClaims.map((claim) => (
                <div key={claim.id} className="discarded-claim-item">
                  <div className="discarded-claim-content">
                    <span className="discarded-speaker">{claim.name || 'Unbekannt'}</span>
                    <span className="discarded-text">{claim.claim}</span>
                  </div>
                  <button
                    className="undiscard-button"
                    onClick={() => onUndiscard(claim.id)}
                    title="Zurück zu Pending"
                  >
                    Zurückholen
                  </button>
                </div>
              ))}
            </div>
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
