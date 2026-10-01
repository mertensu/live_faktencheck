import { Link, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { useSidebar } from './MyChecksSidebar'

const GITHUB_REPO_URL = "https://github.com/mertensu/live_faktencheck"

export function Navigation() {
  const location = useLocation()
  const [visible, setVisible] = useState(true)
  const lastYRef = useRef(0)
  const sb = useSidebar()

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
        {/* Narrow screens: the sidebar is a drawer; this button opens and closes it. */}
        {sb.enabled && (
          <button
            type="button"
            className="nav-sb-toggle"
            aria-expanded={sb.open}
            aria-label="Meine Checks"
            onClick={() => sb.setOpen(!sb.open)}
          >
            {sb.open ? '✕' : '☰'}<span className="nav-sb-label"> Meine Checks</span>
          </button>
        )}
        <Link to="/" className="nav-logo">Live-Faktencheck</Link>
        <div className="nav-links">
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
