import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './App.css'

import { useShows } from './hooks/useShows'
import { Navigation } from './components/Navigation'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { AboutPage } from './pages/AboutPage'
import { FactCheckPage } from './pages/FactCheckPage'

function App() {
  const { shows } = useShows()

  return (
    <BrowserRouter>
      <div className="app">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          {/* Dynamic routes for all episodes */}
          {shows.filter(s => (s.key || s) !== 'test').map(show => {
            const episodeKey = show.key || show
            const showName = show.name || episodeKey.charAt(0).toUpperCase() + episodeKey.slice(1)
            return (
              <Route
                key={episodeKey}
                path={`/${episodeKey}`}
                element={<FactCheckPage showName={showName} showKey={episodeKey} episodeKey={episodeKey} />}
              />
            )
          })}
        </Routes>
        <Footer />
      </div>
    </BrowserRouter>
  )
}

export default App
