import { describe, it, expect, beforeAll, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
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
    const fc = { ...checks[0], kurzfassung: 'Kurzfassung.',
      begruendung: '**Was die Quellen sagen**\n\nLange Begründung.\n\n**Was offen bleibt**\n\nEtwas fehlt.' }
    const { container } = render(<FactCheckStream factChecks={[fc]} />)
    fireEvent.click(container.querySelector('.fcs-card'))
    expect(screen.getByText('Kurzfassung.')).toBeDefined()
    expect(screen.queryByText('Lange Begründung.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Mehr anzeigen' }))
    const panel = screen.getByRole('dialog', { name: 'Prüfergebnis' })
    expect(panel.textContent).toContain('Lange Begründung.')
    expect(panel.textContent).toContain('Erste Aussage')
    expect(panel.querySelector('.claim-detail-lead').textContent).toBe('Kurzfassung.')
    expect([...panel.querySelectorAll('h3.begruendung-heading')].map((h) => h.textContent))
      .toEqual(['Was die Quellen sagen', 'Was offen bleibt'])
    expect(container.querySelector('.fcs-card').className).toMatch(/fcs-open/) // the tap didn't toggle the card
  })

  it('closes the side panel with "Zurück" and leaves the page usable', async () => {
    vi.useFakeTimers()
    try {
      render(<FactCheckStream factChecks={[{ ...checks[0], kurzfassung: 'Kurz.', begruendung: 'Lang.' }]} />)
      fireEvent.click(screen.getByRole('button', { name: 'Mehr anzeigen' }))
      expect(document.body.style.overflow).toBe('hidden')
      fireEvent.click(screen.getByRole('button', { name: '← Zurück' }))
      act(() => { vi.advanceTimersByTime(300) }) // no animationend needed
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(document.querySelector('.claim-detail-backdrop')).toBeNull()
      expect(document.body.style.overflow).toBe('')
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows the long version alone when there is no short one', () => {
    render(<FactCheckStream factChecks={[{ ...checks[0], begruendung: 'Lange Begründung.' }]} />)
    expect(screen.getByText('Lange Begründung.')).toBeDefined()
    expect(screen.queryByRole('button', { name: 'Mehr anzeigen' })).toBeNull()
  })
})
