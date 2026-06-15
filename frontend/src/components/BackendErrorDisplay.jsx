export function BackendErrorDisplay({ error }) {
  if (!error) return null

  return (
    <div className="backend-error">
      <p className="backend-error-message">Coming soon</p>
    </div>
  )
}
