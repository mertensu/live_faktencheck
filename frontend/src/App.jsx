import { BrowserRouter, Routes, Route, useParams, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import './App.css'

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

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Navigation />
        <ScrollToHash />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/trusted-domains" element={<TrustedDomainsPage />} />
          <Route path="/new" element={<NewSessionPage />} />
          <Route path="/pruefen" element={<QuickCheckPage />} />
          <Route path="/:episodeKey" element={<EpisodeRoute />} />
        </Routes>
        <Footer />
      </div>
    </BrowserRouter>
  )
}

export default App
