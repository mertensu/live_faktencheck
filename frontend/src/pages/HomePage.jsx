import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AccessUnlock } from '../components/AccessUnlock'
import { LandingIllustration } from '../components/LandingIllustration'
import { PipelineAnimation } from '../components/PipelineAnimation'
import { getAccessCode } from '../services/api'

export function HomePage() {
  const navigate = useNavigate()
  const [askCode, setAskCode] = useState(false)
  const unlockRef = useRef(null)

  // "Jetzt starten": with a stored code straight into "Mein Bereich"; otherwise ask for one.
  const start = () => {
    if (getAccessCode()) navigate('/mein-bereich')
    else setAskCode(true)
  }

  useEffect(() => { if (askCode) unlockRef.current?.focus() }, [askCode])

  // After entering a code, go on into "Mein Bereich"; it shows the limit popup there.
  const handleUnlock = useCallback((_code, _name, data) => {
    navigate('/mein-bereich', data ? { state: { limitInfo: data } } : undefined)
  }, [navigate])

  return (
    <div className="home-page landing">
      <section className="landing-hero">
        <div className="landing-copy">
          <h1 className="landing-title">Fakten prüfen,<br /> <span className="landing-title-line">während gesprochen wird.</span></h1>
          <div className="landing-lead">
            <p><strong>KI-gestützte Faktenchecks</strong> zu Politik, Wirtschaft und Gesellschaft in Deutschland.</p>
            <p className="landing-lead-muted">
              Ob Talkshow, Interview oder Debatte: Jede überprüfbare Aussage wird live markiert und mit
              vertrauenswürdigen Quellen bewertet, in wenigen Sekunden.
            </p>
          </div>
          <button type="button" className="landing-cta" onClick={start} aria-expanded={askCode}>
            Jetzt starten <span aria-hidden="true">→</span>
          </button>
          {askCode && (
            <div className="landing-code">
              <p className="landing-code-label">Zugangscode eingeben:</p>
              <AccessUnlock ref={unlockRef} unlocked={false} onUnlock={handleUnlock} />
            </div>
          )}
        </div>
        <LandingIllustration />
      </section>
      <section id="so-funktioniert-es" className="landing-how">
        <div className="landing-how-inner">
          <p className="landing-how-eyebrow">So funktioniert es</p>
          <h2 className="landing-how-title">Vom gesprochenen Satz zur Bewertung</h2>
          <p className="landing-how-lead">Klicken Sie sich an einem Beispiel durch die sechs Schritte.</p>
          <div className="landing-how-card">
            <PipelineAnimation />
          </div>
          <Link className="landing-how-more" to="/about">Mehr zum Projekt →</Link>
        </div>
      </section>
    </div>
  )
}
