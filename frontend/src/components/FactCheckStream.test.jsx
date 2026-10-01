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
