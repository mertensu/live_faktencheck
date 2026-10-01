import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteSession, fetchMySessions, getAccessCode } from '../services/api'
import { getConsistencyColor } from '../components/ClaimCard'

// "Meine Checks": the sessions created with the stored access code. Only claims and
// verdicts are stored (the transcript never leaves the browser), so each entry links
// to the session page, which shows its results stream.

const createdLabel = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const COUNTS = [
  { key: 'hoch', label: 'hoch' },
  { key: 'niedrig', label: 'niedrig' },
  { key: 'unklar', label: 'unklar' },
]

export function MyChecksPage() {
  const hasCode = Boolean(getAccessCode())
  const [sessions, setSessions] = useState(null)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(null)

  const handleDelete = async (s) => {
    const ok = window.confirm(
      `„${s.title || 'Ohne Titel'}“ mit allen Aussagen und Bewertungen endgültig löschen?\n\n` +
      'Aus Sicherungskopien verschwindet der Check spätestens nach 30 Tagen.'
    )
    if (!ok) return
    setDeleting(s.session_id)
    try {
      await deleteSession(s.session_id)
      setSessions((prev) => prev.filter((x) => x.session_id !== s.session_id))
    } catch (err) {
      window.alert(err.message || 'Löschen fehlgeschlagen')
    } finally {
      setDeleting(null)
    }
  }

  useEffect(() => {
    if (!hasCode) return
    let alive = true
    fetchMySessions()
      .then((data) => { if (alive) setSessions(data) })
      .catch((err) => { if (alive) setError(err.message || 'Laden fehlgeschlagen') })
    return () => { alive = false }
  }, [hasCode])

  let body
  if (!hasCode) {
    body = (
      <p className="examples-intro">
        Mit einem Zugangscode siehst du hier deine eigenen Checks. <Link to="/">Zur Startseite</Link>
      </p>
    )
  } else if (error) {
    body = <p className="form-error">{error}</p>
  } else if (sessions === null) {
    body = (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    )
  } else if (sessions.length === 0) {
    body = (
      <p className="examples-intro">
        Noch keine eigenen Checks. <Link to="/new">Live-Faktencheck starten</Link>
      </p>
    )
  } else {
    body = (
      <div className="shows-list">
        {sessions.map((s) => (
          <div key={s.session_id} className="my-check-row">
            <Link to={`/${s.session_id}`} className="show-item">
              <div className="show-item-content">
                <span className="show-name">{s.title || 'Ohne Titel'}</span>
                <span className="show-info">
                  {[s.date, createdLabel(s.created_at)].filter(Boolean).join(' · ')}
                </span>
                <span className="my-check-counts">
                  <span>{s.claims === 1 ? '1 Aussage' : `${s.claims} Aussagen`}</span>
                  {COUNTS.filter(({ key }) => s[key] > 0).map(({ key, label }) => (
                    <span key={key} className="my-check-count">
                      <span className="fcs-dot" style={{ background: getConsistencyColor(key) }} />
                      {s[key]} {label}
                    </span>
                  ))}
                </span>
              </div>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            </Link>
            <button
              type="button"
              className="my-check-delete"
              onClick={() => handleDelete(s)}
              disabled={deleting === s.session_id}
              aria-label={`${s.title || 'Check'} löschen`}
            >
              {deleting === s.session_id ? 'Lösche …' : 'Löschen'}
            </button>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="home-page">
      <section className="examples-section">
        <h2 className="examples-title">Meine Checks</h2>
        {hasCode && (
          <p className="examples-intro">
            Deine Sitzungen mit geprüften Aussagen und Bewertungen. Das Transkript wird nicht gespeichert.
          </p>
        )}
        {body}
      </section>
    </div>
  )
}
