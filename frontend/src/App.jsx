import { BrowserRouter, Routes, Route, useParams } from 'react-router-dom'
import './App.css'

import { Navigation } from './components/Navigation'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { AboutPage } from './pages/AboutPage'
import { FactCheckPage } from './pages/FactCheckPage'

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
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/:episodeKey" element={<EpisodeRoute />} />
        </Routes>
        <Footer />
      </div>
    </BrowserRouter>
  )
}

export default App
