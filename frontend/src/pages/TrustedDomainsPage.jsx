import { useState, useEffect } from 'react'
import { BACKEND_URL, safeJsonParse } from '../services/api'

export function TrustedDomainsPage() {
  const [categories, setCategories] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/trusted-domains`)
      .then(r => safeJsonParse(r, 'trusted-domains'))
      .then(setCategories)
      .catch(e => setError(e.message))
  }, [])

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Vertrauenswürdige Quellen</h1>
        <p>
          Um Halluzinationen des KI-Modells zu minimieren, wird die Web-Recherche auf folgende
          vertrauenswürdige Domains beschränkt. Die Liste wird kontinuierlich gepflegt und erweitert.
        </p>

        {error && <p style={{ color: 'var(--color-error, #c00)' }}>Fehler beim Laden: {error}</p>}

        {categories && Object.entries(categories).map(([category, domains]) => (
          <div key={category} className="trusted-domains-category">
            <h2>{category}</h2>
            <ul className="trusted-domains-list">
              {domains.map(domain => (
                <li key={domain}>
                  <a
                    href={`https://${domain}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {domain}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  )
}
