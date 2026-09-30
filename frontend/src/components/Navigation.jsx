import { Link, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { ACCESS_CODE_EVENT, getAccessCode } from '../services/api'

const GITHUB_REPO_URL = "https://github.com/mertensu/live_faktencheck"

export function Navigation() {
  const location = useLocation()
  const [visible, setVisible] = useState(true)
  const lastYRef = useRef(0)
  // "Meine Checks" only makes sense with a stored code — it lists that code's sessions.
  const [hasCode, setHasCode] = useState(() => Boolean(getAccessCode()))

  useEffect(() => {
    const sync = () => setHasCode(Boolean(getAccessCode()))
    window.addEventListener(ACCESS_CODE_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(ACCESS_CODE_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  useEffect(() => {
    const handleScroll = () => {
      const currentY = window.scrollY
      setVisible(currentY < lastYRef.current || currentY < 60)
      lastYRef.current = currentY
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <nav className={`main-navigation${visible ? '' : ' main-navigation--hidden'}`}>
      <div className="nav-container">
        <Link to="/" className="nav-logo">Live-Faktencheck</Link>
        <div className="nav-links">
          {hasCode && (
            <Link to="/meine-checks" className={location.pathname === '/meine-checks' ? 'active' : ''}>
              Meine Checks
            </Link>
          )}
          <Link to="/beispiele" className={location.pathname === '/beispiele' ? 'active' : ''}>
            Beispiele
          </Link>
          <Link to="/about" className={location.pathname === '/about' ? 'active' : ''}>
            About
          </Link>
        </div>
      </div>
    </nav>
  )
}
