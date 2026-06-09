import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession } from '../services/api'

export function NewSessionPage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [guests, setGuests] = useState('')
  const [context, setContext] = useState('')
  const [referenceLinks, setReferenceLinks] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        title,
        date,
        guests: guests.split('\n').map(s => s.trim()).filter(Boolean),
        context,
        reference_links: referenceLinks.split('\n').map(s => s.trim()).filter(Boolean),
        type: 'show',
      }
      const result = await createSession(payload)
      if (!result?.session_id) {
        throw new Error('Keine Session-ID erhalten')
      }
      navigate('/' + result.session_id)
    } catch (err) {
      setError(err.message || 'Fehler beim Erstellen der Session')
      setSubmitting(false)
    }
  }

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Neue Session erstellen</h1>
        <form onSubmit={handleSubmit} className="new-session-form">
          <div className="form-field">
            <label htmlFor="session-title">Titel *</label>
            <input
              id="session-title"
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              required
              placeholder="z.B. Maischberger 2026-02-09"
            />
          </div>

          <div className="form-field">
            <label htmlFor="session-date">Datum</label>
            <input
              id="session-date"
              type="text"
              value={date}
              onChange={e => setDate(e.target.value)}
              placeholder="z.B. 9. Februar 2026"
            />
          </div>

          <div className="form-field">
            <label htmlFor="session-guests">Gäste (eine Person pro Zeile, Format: Name (Rolle))</label>
            <textarea
              id="session-guests"
              value={guests}
              onChange={e => setGuests(e.target.value)}
              rows={5}
              placeholder={"Alice Müller (SPD-Politikerin)\nBob Schmidt (Journalist)"}
            />
          </div>

          <div className="form-field">
            <label htmlFor="session-context">Kontext</label>
            <textarea
              id="session-context"
              value={context}
              onChange={e => setContext(e.target.value)}
              rows={4}
              placeholder="Thema und Hintergrund der Sendung..."
            />
          </div>

          <div className="form-field">
            <label htmlFor="session-refs">Referenz-Links (eine URL pro Zeile)</label>
            <textarea
              id="session-refs"
              value={referenceLinks}
              onChange={e => setReferenceLinks(e.target.value)}
              rows={4}
              placeholder={"https://example.com/artikel-1\nhttps://example.com/artikel-2"}
            />
          </div>

          {error && (
            <p className="form-error">{error}</p>
          )}

          <div className="form-actions">
            <button
              type="submit"
              className="action-button primary"
              disabled={submitting}
            >
              {submitting ? 'Wird erstellt...' : 'Session erstellen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
