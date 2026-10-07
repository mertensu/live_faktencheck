import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation, useNavigationType } from 'react-router-dom'
import { useEffect } from 'react'
import './App.css'

import { getAccessCode } from './services/api'
import { Navigation } from './components/Navigation'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { MyAreaPage } from './pages/MyAreaPage'
import { AboutPage } from './pages/AboutPage'
import { TrustedDomainsPage } from './pages/TrustedDomainsPage'
import { FactCheckPage } from './pages/FactCheckPage'
import { NewSessionPage } from './pages/NewSessionPage'
import { ExamplesPage } from './pages/ExamplesPage'
import { MyChecksSidebar, SidebarProvider, sidebarAppClasses, useSidebar } from './components/MyChecksSidebar'
import { useHasAccessCode } from './hooks/useHasAccessCode'

// Scroll to an in-page anchor (e.g. /about#section), or to the top when a link opens a new
// page; BrowserRouter does neither natively. Back/forward (POP) keeps the browser's position.
function ScrollOnNavigate() {
  const { pathname, hash } = useLocation()
  const navType = useNavigationType()
  useEffect(() => {
    if (hash) {
      const el = document.getElementById(hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth' })
    } else if (navType !== 'POP') {
      window.scrollTo(0, 0)
    }
  }, [pathname, hash, navType])
  return null
}

function EpisodeRoute() {
  const { episodeKey } = useParams()
  const prefix = episodeKey.split('-')[0]
  const showName = prefix.charAt(0).toUpperCase() + prefix.slice(1)
  // Keyed so switching checks from the sidebar starts a fresh page (stream, results, config).
  return <FactCheckPage key={episodeKey} showName={showName} episodeKey={episodeKey} />
}

// Static top-level routes; anything else is an episode/session page.
const STATIC_ROUTES = new Set(['/', '/about', '/trusted-domains', '/new', '/beispiele', '/meine-checks', '/mein-bereich'])

// Operator pages that show the "Meine Checks" sidebar (besides every session page).
const SIDEBAR_ROUTES = new Set(['/mein-bereich', '/new'])

function AppInner() {
  const { pathname } = useLocation()
  const hasCode = useHasAccessCode()
  // A viewer opening a shared session link (no access code) gets a stripped-down
  // public page: just the fact-check stream, no site nav or footer chrome. The
  // moderator (holds a code) keeps the full app.
  const isEpisodeRoute = !STATIC_ROUTES.has(pathname)
  const viewerMinimal = isEpisodeRoute && !getAccessCode()
  const sidebarEnabled = hasCode && (isEpisodeRoute || SIDEBAR_ROUTES.has(pathname))

  return (
    <SidebarProvider enabled={sidebarEnabled}>
      <AppShell viewerMinimal={viewerMinimal} />
    </SidebarProvider>
  )
}

function AppShell({ viewerMinimal }) {
  const sb = useSidebar()
  return (
    <div className={`app${viewerMinimal ? ' app--viewer' : ''}${sidebarAppClasses(sb)}`}>
      {!viewerMinimal && <Navigation />}
      <MyChecksSidebar />
      <ScrollOnNavigate />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/trusted-domains" element={<TrustedDomainsPage />} />
        <Route path="/new" element={<NewSessionPage />} />
        <Route path="/beispiele" element={<ExamplesPage />} />
        <Route path="/mein-bereich" element={<MyAreaPage />} />
        {/* The list lives in the sidebar of "Mein Bereich" now; keep old links working. */}
        <Route path="/meine-checks" element={<Navigate to="/mein-bereich" replace />} />
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
