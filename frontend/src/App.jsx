import { BrowserRouter, Routes, Route, useParams, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import './App.css'

import { getAccessCode } from './services/api'
import { Navigation } from './components/Navigation'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { AboutPage } from './pages/AboutPage'
import { TrustedDomainsPage } from './pages/TrustedDomainsPage'
import { FactCheckPage } from './pages/FactCheckPage'
import { NewSessionPage } from './pages/NewSessionPage'
import { QuickCheckPage } from './pages/QuickCheckPage'

// Scroll to an in-page anchor (e.g. nav "Beispiele" → /#beispiele); BrowserRouter
// does not do this natively.
function ScrollToHash() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    const el = document.getElementById(hash.slice(1))
    if (el) el.scrollIntoView({ behavior: 'smooth' })
  }, [hash])
  return null
}

function EpisodeRoute() {
  const { episodeKey } = useParams()
  const prefix = episodeKey.split('-')[0]
  const showName = prefix.charAt(0).toUpperCase() + prefix.slice(1)
  return <FactCheckPage showName={showName} episodeKey={episodeKey} />
}

// Static top-level routes; anything else is an episode/session page.
const STATIC_ROUTES = new Set(['/', '/about', '/trusted-domains', '/new', '/pruefen'])

function AppInner() {
  const { pathname } = useLocation()
  // A viewer opening a shared session link (no access code) gets a stripped-down
  // public page: just the fact-check stream, no site nav or footer chrome. The
  // moderator (holds a code) keeps the full app.
  const isEpisodeRoute = !STATIC_ROUTES.has(pathname)
  const viewerMinimal = isEpisodeRoute && !getAccessCode()

  return (
    <div className={`app${viewerMinimal ? ' app--viewer' : ''}`}>
      {!viewerMinimal && <Navigation />}
      <ScrollToHash />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/trusted-domains" element={<TrustedDomainsPage />} />
        <Route path="/new" element={<NewSessionPage />} />
        <Route path="/pruefen" element={<QuickCheckPage />} />
        <Route path="/:episodeKey" element={<EpisodeRoute />} />
      </Routes>
      {viewerMinimal ? <Footer slim /> : <Footer />}
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  )
}

export default App
