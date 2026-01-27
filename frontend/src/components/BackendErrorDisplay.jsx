export function BackendErrorDisplay({ error }) {
  if (!error) return null

  return (
    <div className="backend-error">
      <h3 className="backend-error-title">Backend-Verbindungsfehler</h3>
      <p className="backend-error-message">{error.message}</p>
      <details className="backend-error-details">
        <summary>Details</summary>
        <div className="backend-error-info">
          <p><strong>Backend URL:</strong> {error.backendUrl}</p>
          <p><strong>Episode:</strong> {error.episodeKey || 'N/A'}</p>
          <p className="backend-error-hint">
            Bitte uberprufe, ob das Backend lauft und die URL korrekt ist.
          </p>
        </div>
      </details>
    </div>
  )
}
