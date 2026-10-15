import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FactCheckStream } from './FactCheckStream'

const checks = [
  { id: 1, sprecher: 'Anna', behauptung: 'Erste Aussage', consistency: 'hoch', timestamp: '2026-09-30T20:00:00', status: 'done', quellen: [] },
  { id: 2, sprecher: 'Bert', behauptung: 'Zweite Aussage', consistency: 'niedrig', timestamp: '2026-09-30T20:10:00', status: 'done', quellen: [] },
]

const claimOrder = () => [...document.querySelectorAll('.fcs-claim')].map((el) => el.textContent)

describe('FactCheckStream order toggle', () => {
  beforeAll(() => {
    window.matchMedia ??= () => ({ matches: false })
  })

  it('shows newest first and flips to oldest first', () => {
    render(<FactCheckStream factChecks={checks} />)
    expect(claimOrder()).toEqual(['Zweite Aussage', 'Erste Aussage'])
    fireEvent.click(screen.getByRole('button', { name: /neueste zuerst/i }))
    expect(claimOrder()).toEqual(['Erste Aussage', 'Zweite Aussage'])
    expect(screen.getByRole('button', { name: /älteste zuerst/i })).toBeDefined()
  })
})

describe('FactCheckStream reasoning', () => {
  beforeAll(() => {
    window.matchMedia ??= () => ({ matches: false })
    window.scrollTo = () => {}
  })

  it('shows the short version in the card and the long one in a side panel', () => {
    const fc = { ...checks[0], kurzfassung: 'Kurzfassung.', begruendung: 'Lange Begründung.' }
    const { container } = render(<FactCheckStream factChecks={[fc]} />)
    fireEvent.click(container.querySelector('.fcs-card'))
    expect(screen.getByText('Kurzfassung.')).toBeDefined()
    expect(screen.queryByText('Lange Begründung.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Mehr anzeigen' }))
    const panel = screen.getByRole('dialog', { name: 'Prüfergebnis' })
    expect(panel.textContent).toContain('Lange Begründung.')
    expect(panel.textContent).toContain('Erste Aussage')
    expect(container.querySelector('.fcs-card').className).toMatch(/fcs-open/) // the tap didn't toggle the card
  })

  it('closes the side panel with "Zurück" (at once under reduced motion)', () => {
    const matchMedia = window.matchMedia
    window.matchMedia = (q) => ({ matches: q.includes('reduced-motion') })
    try {
      render(<FactCheckStream factChecks={[{ ...checks[0], kurzfassung: 'Kurz.', begruendung: 'Lang.' }]} />)
      fireEvent.click(screen.getByRole('button', { name: 'Mehr anzeigen' }))
      fireEvent.click(screen.getByRole('button', { name: '← Zurück' }))
      expect(screen.queryByRole('dialog')).toBeNull()
    } finally {
      window.matchMedia = matchMedia
    }
  })

  it('shows the long version alone when there is no short one', () => {
    render(<FactCheckStream factChecks={[{ ...checks[0], begruendung: 'Lange Begründung.' }]} />)
    expect(screen.getByText('Lange Begründung.')).toBeDefined()
    expect(screen.queryByRole('button', { name: 'Mehr anzeigen' })).toBeNull()
  })
})
