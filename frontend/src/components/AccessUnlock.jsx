import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { validateCode, getAccessCode, setAccessCode } from '../services/api'

export const AccessUnlock = forwardRef(function AccessUnlock({ unlocked, name, onUnlock }, ref) {
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
  }))

  // Render unlocked immediately if a code is already stored.
  useEffect(() => {
    const stored = getAccessCode()
    if (stored && !unlocked) onUnlock(stored, null)
  }, [unlocked, onUnlock])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    const trimmed = code.trim()
    try {
      const data = await validateCode(trimmed)
      setAccessCode(trimmed)
      onUnlock(trimmed, data?.name ?? null, data)
      setCode('')
    } catch (err) {
      const msg = err.message || 'Unbekannter Fehler'
      setError(/401|403|Zugangscode/i.test(msg) ? 'Ungültiger Zugangscode' : msg)
      setCode('')
    } finally {
      setSubmitting(false)
    }
  }

  if (unlocked) {
    return (
      <section className="access-unlock access-unlock--done">
        <p className="access-unlock-status">
          Freigeschaltet{name ? ` als ${name}` : ''}.
        </p>
      </section>
    )
  }

  return (
    <section className="access-unlock">
      <form onSubmit={handleSubmit} className="access-unlock-form">
        <input
          ref={inputRef}
          type="password"
          value={code}
          onChange={e => setCode(e.target.value)}
          autoComplete="off"
          placeholder="Zugangscode"
          aria-label="Zugangscode"
          className="access-unlock-input"
        />
        <button type="submit" className="action-button primary" disabled={submitting}>
          {submitting ? 'Prüfe …' : 'Freischalten'}
        </button>
      </form>
      {error && <p className="form-error">{error}</p>}
    </section>
  )
})
