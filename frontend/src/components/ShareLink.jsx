import { useState } from 'react'

// Shareable public link to the live stream, shown to the moderator so they can
// hand the view-only URL to others. The link is just the session page without
// any admin flag — anyone opening it sees the read-only Fokus-Stream.
export function ShareLink({ sessionId }) {
  const [copied, setCopied] = useState(false)
  const url = `${window.location.origin}/${sessionId}`
  const shown = url.replace(/^https?:\/\//, '')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // Fallback for non-secure contexts / older browsers.
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* give up silently */ }
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="share-link">
      <span className="share-link-label">Live-Link teilen</span>
      <button
        type="button"
        className="share-link-btn"
        onClick={copy}
        aria-label={`Live-Link kopieren: ${shown}`}
        title="Link kopieren"
      >
        <span className="share-link-url">{shown}</span>
        {copied ? (
          <svg className="share-link-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        ) : (
          <svg className="share-link-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
        )}
      </button>
      <span className={`share-link-copied${copied ? ' share-link-copied--show' : ''}`} role="status" aria-live="polite">
        {copied ? 'Kopiert!' : ''}
      </span>
    </div>
  )
}
