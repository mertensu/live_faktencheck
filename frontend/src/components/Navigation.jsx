import { Link, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'

const GITHUB_REPO_URL = "https://github.com/mertensu/live_faktencheck"

export function Navigation() {
  const location = useLocation()
  const [visible, setVisible] = useState(true)
  const lastYRef = useRef(0)

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
          <Link to="/about" className={location.pathname === '/about' ? 'active' : ''}>
            About
          </Link>
        </div>
      </div>
    </nav>
  )
}
