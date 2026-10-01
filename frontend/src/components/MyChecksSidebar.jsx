import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { deleteSession, fetchMySessions } from '../services/api'
import { getConsistencyColor } from './ClaimCard'

// "Meine Checks" sidebar for operators (a code is stored). Docked on wide screens and
// collapsed to a thin rail while a Live-Check runs, so the transcript gets the width;
// on narrow screens it is a drawer behind the "☰ Meine Checks" nav button. Only claims
// and verdicts are stored (the transcript never leaves the browser), so each entry
// opens the session page with its results stream.

const COLLAPSED_KEY = 'fc_sidebar_collapsed'

const readCollapsed = () => {
  try { return localStorage.getItem(COLLAPSED_KEY) === '1' } catch { return false }
}
const writeCollapsed = (v) => {
  try { localStorage.setItem(COLLAPSED_KEY, v ? '1' : '0') } catch { /* ignore storage errors */ }
}

const SidebarContext = createContext(null)

export function SidebarProvider({ enabled, children }) {
  const [live, setLive] = useState(false)
  const [collapsed, setCollapsedState] = useState(readCollapsed)
  const [open, setOpen] = useState(false)  // drawer (narrow) or overlay over the rail (wide)
  const { pathname } = useLocation()

  const setCollapsed = useCallback((v) => { setCollapsedState(v); writeCollapsed(v); setOpen(false) }, [])

  // Close the drawer on navigation, and when the rail goes away again.
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => { if (!live && !collapsed) setOpen(false) }, [live, collapsed])

  const value = useMemo(() => ({
    enabled, live, setLive, collapsed, setCollapsed, open, setOpen,
    rail: enabled && (live || collapsed),
  }), [enabled, live, collapsed, setCollapsed, open])

  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>
}

const NOOP = { enabled: false, live: false, setLive: () => {}, open: false, setOpen: () => {}, rail: false }

export const useSidebar = () => useContext(SidebarContext) || NOOP

// Classes for the .app wrapper so the page makes room for the docked sidebar or rail.
export function sidebarAppClasses(sb) {
  if (!sb.enabled) return ''
  return [' app--sb', sb.rail && ' app--sb-rail', sb.open && ' app--sb-open'].filter(Boolean).join('')
}

const monthLabel = (iso) => {
  const d = new Date(iso || '')
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' })
}

const createdLabel = (iso) => {
  const d = new Date(iso || '')
  if (isNaN(d.getTime())) return ''
  const day = d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
  const time = d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
  return `${day} · ${time}`
}

const VERDICT_KEYS = ['hoch', 'niedrig', 'unklar']

function SessionItem({ s, current, live, onDelete }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const isCurrent = current === s.session_id
  // Leaving the page stops the live stream, so other checks are locked while live.
  const locked = live && !isCurrent

  const doDelete = async () => {
    setBusy(true)
    setError(null)
    try {
      await deleteSession(s.session_id)
      onDelete(s.session_id)
    } catch (err) {
      setError(err.message || 'Löschen fehlgeschlagen')
      setBusy(false)
    }
  }

  const body = (
    <>
      <span className="sb-item-title">{s.title || 'Ohne Titel'}</span>
      <span className="sb-item-meta">
        {live && isCurrent && <span className="live-badge">LIVE</span>}
        <span>{createdLabel(s.created_at)}</span>
        <span>{s.claims === 1 ? '1 Aussage' : `${s.claims} Aussagen`}</span>
        <span className="sb-dots">
          {VERDICT_KEYS.filter((k) => s[k] > 0).map((k) => (
            <span key={k} className="fcs-dot" style={{ background: getConsistencyColor(k) }} title={`${s[k]} ${k}`} />
          ))}
        </span>
      </span>
    </>
  )

  return (
    <div className={`sb-item${isCurrent ? ' sb-item--on' : ''}${locked ? ' sb-item--locked' : ''}`}>
      <div className="sb-item-row">
        {locked ? (
          <span className="sb-item-link" aria-disabled="true">{body}</span>
        ) : (
          <Link to={`/${s.session_id}`} className="sb-item-link">{body}</Link>
        )}
        {!live && (
          <button
            type="button"
            className="sb-more"
            aria-expanded={confirming}
            aria-label={`${s.title || 'Check'} löschen`}
            title="Löschen"
            onClick={() => setConfirming((c) => !c)}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
            </svg>
          </button>
        )}
      </div>
      {confirming && !live && (
        <div className="sb-confirm" role="group" aria-label="Löschen bestätigen">
          <p>Check mit allen Aussagen und Bewertungen endgültig löschen? Aus Sicherungskopien verschwindet er spätestens nach 30 Tagen.</p>
          <div className="sb-confirm-actions">
            <button type="button" className="sb-confirm-delete" onClick={doDelete} disabled={busy}>
              {busy ? 'Lösche …' : 'Löschen'}
            </button>
            <button type="button" className="sb-confirm-cancel" onClick={() => setConfirming(false)} disabled={busy}>
              Abbrechen
            </button>
          </div>
          {error && <p className="form-error">{error}</p>}
        </div>
      )}
    </div>
  )
}

export function MyChecksSidebar() {
  const sb = useSidebar()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState(null)
  const [error, setError] = useState(null)
  const current = pathname.slice(1)

  // Reload on navigation and when a live run ends, so new checks and counts show up.
  useEffect(() => {
    if (!sb.enabled) return
    let alive = true
    fetchMySessions()
      .then((data) => { if (alive) { setSessions(data); setError(null) } })
      .catch((err) => { if (alive) setError(err.message || 'Laden fehlgeschlagen') })
    return () => { alive = false }
  }, [sb.enabled, pathname, sb.live])

  if (!sb.enabled) return null

  const handleDeleted = (id) => {
    setSessions((prev) => (prev || []).filter((x) => x.session_id !== id))
    if (id === current) navigate('/mein-bereich')
  }

  const groups = []
  for (const s of sessions || []) {
    const m = monthLabel(s.created_at)
    if (!groups.length || groups[groups.length - 1].month !== m) groups.push({ month: m, items: [] })
    groups[groups.length - 1].items.push(s)
  }

  return (
    <>
      {sb.rail && (
        <aside className="sb-rail" aria-label="Meine Checks (eingeklappt)">
          <button
            type="button"
            className="sb-icon-btn"
            title="Meine Checks einblenden"
            aria-label="Meine Checks einblenden"
            onClick={() => (sb.live ? sb.setOpen(!sb.open) : sb.setCollapsed(false))}
          >
            ☰
          </button>
          {sessions && <span className="sb-rail-count">{sessions.length}</span>}
        </aside>
      )}
      {sb.open && <div className="sb-scrim" onClick={() => sb.setOpen(false)} aria-hidden="true" />}
      <aside className="sb" aria-label="Meine Checks">
        <div className="sb-head">
          <span className="sb-title">Meine Checks</span>
          {!sb.live && (
            <button
              type="button"
              className="sb-icon-btn sb-collapse"
              title="Liste einklappen"
              aria-label="Liste einklappen"
              onClick={() => sb.setCollapsed(true)}
            >
              «
            </button>
          )}
          <button
            type="button"
            className="sb-icon-btn sb-close"
            title="Schließen"
            aria-label="Meine Checks schließen"
            onClick={() => sb.setOpen(false)}
          >
            ✕
          </button>
        </div>
        {sb.live ? (
          <p className="sb-note">Live-Check läuft. Wechseln erst nach ◉ Live stoppen.</p>
        ) : (
          <Link to="/new" className="sb-new">＋ Neuer Check</Link>
        )}
        <div className="sb-list">
          {error && <p className="form-error sb-note">{error}</p>}
          {sessions && sessions.length === 0 && (
            <p className="sb-note">Noch keine eigenen Checks.</p>
          )}
          {groups.map((g) => (
            <div key={g.month} className="sb-group">
              {g.month && <div className="sb-month">{g.month}</div>}
              {g.items.map((s) => (
                <SessionItem key={s.session_id} s={s} current={current} live={sb.live} onDelete={handleDeleted} />
              ))}
            </div>
          ))}
        </div>
      </aside>
    </>
  )
}
