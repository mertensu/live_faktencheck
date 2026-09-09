export function BackendErrorDisplay({ error }) {
  if (!error) return null

  return (
    <div className="backend-error">
      <p className="backend-error-message">Verbindung zum Backend unterbrochen</p>
      <p className="backend-error-hint">
        Die Ergebnisse konnten gerade nicht geladen werden. Es wird automatisch
        erneut versucht.
      </p>
    </div>
  )
}
