import { useState } from "react"

export function Footer() {
  const [showImpressum, setShowImpressum] = useState(false)

  return (
    <footer className="app-footer">
      <div className="footer-content">
        <p className="footer-disclaimer">
          Die hier dargestellten Faktenchecks werden automatisch mit Hilfe von
          Künstlicher Intelligenz (KI) generiert. Die Inhalte können Fehler enthalten und sollten nicht
          als alleinige Grundlage für Entscheidungen verwendet werden. Es wird keine Gewähr für
          die Richtigkeit, Vollständigkeit oder Aktualität der Informationen übernommen.
        </p>
        <p className="footer-meta">
          Diese Seite dient ausschließlich zu Informationszwecken. Bei Fragen oder Anmerkungen wenden Sie sich bitte an info@live-faktencheck.de.
        </p>
        <p className="footer-meta">
          <button className="impressum-button" onClick={() => setShowImpressum(true)}>
            Impressum
          </button>
        </p>
      </div>

      {showImpressum && (
        <div className="impressum-overlay" onClick={() => setShowImpressum(false)}>
          <div className="impressum-modal" onClick={e => e.stopPropagation()}>
            <button className="impressum-close" onClick={() => setShowImpressum(false)}>×</button>
            <h2>Impressum</h2>
            <p>
              Ulf Mertens<br />
              c/o Postflex #PFX-006-869<br />
              Emsdettener Str. 10<br />
              48268 Greven
            </p>
            <p className="impressum-note">
              Hinweis: Pakete und Päckchen können unter dieser Anschrift nicht angenommen werden.
            </p>
          </div>
        </div>
      )}
    </footer>
  )
}
