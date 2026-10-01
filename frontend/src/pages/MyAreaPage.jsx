import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LimitInfoModal } from '../components/LimitInfoModal'
import { useSidebar } from '../components/MyChecksSidebar'
import { useHasAccessCode } from '../hooks/useHasAccessCode'

// "Mein Bereich": the operator's home after unlocking. The list of own checks and
// "+ Neuer Check" live in the sidebar; this page only says where to start.
export function MyAreaPage() {
  const hasCode = useHasAccessCode()
  const sb = useSidebar()
  const location = useLocation()
  const navigate = useNavigate()
  // Right after entering a code on the landing page: show the code's limits once.
  const limitInfo = location.state?.limitInfo
  const closeLimitInfo = () => navigate(location.pathname, { replace: true, state: null })

  return (
    <div className="home-page">
      {limitInfo && <LimitInfoModal info={limitInfo} onClose={closeLimitInfo} />}
      <section className="examples-section my-area">
        <h2 className="examples-title">Mein Bereich</h2>
        {hasCode ? (
          <>
            <p className="examples-intro">
              Unter „Meine Checks“ findest du deine bisherigen Faktenchecks mit allen geprüften
              Aussagen und Bewertungen. Mit „+ Neuer Check“ legst du einen neuen Faktencheck an.
              Das Transkript wird nicht gespeichert.
            </p>
            {/* Narrow screens: the list is a drawer, so offer a direct way to open it. */}
            <button type="button" className="action-button primary my-area-open" onClick={() => sb.setOpen(true)}>
              ☰ Meine Checks öffnen
            </button>
          </>
        ) : (
          <p className="examples-intro">
            Mit einem Zugangscode siehst du hier deine eigenen Checks. <Link to="/">Zur Startseite</Link>
          </p>
        )}
      </section>
    </div>
  )
}
