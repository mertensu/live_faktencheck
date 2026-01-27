import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './App.css'

import { useShows } from './hooks/useShows'
import { Navigation } from './components/Navigation'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { AboutPage } from './pages/AboutPage'
import { ShowPage } from './pages/ShowPage'
import { FactCheckPage } from './pages/FactCheckPage'

function App() {
  const { shows } = useShows()

  return (
    <BrowserRouter basename={import.meta.env.PROD ? '/live_faktencheck' : ''}>
      <div className="app">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/test" element={<FactCheckPage showName="Test" showKey="test" episodeKey="test" />} />
          {/* Dynamic routes for all shows */}
          {shows.filter(s => (s.key || s) !== 'test').map(show => {
            const showKey = show.key || show
            return (
              <Route
                key={showKey}
                path={`/${showKey}/:episode?`}
                element={<ShowPage showKey={showKey} />}
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
