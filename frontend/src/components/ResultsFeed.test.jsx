import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ResultsFeed } from './ResultsFeed'

describe('ResultsFeed', () => {
  it('shows the empty state when there are no results', () => {
    render(<ResultsFeed factChecks={[]} onSelect={() => {}} />)
    expect(screen.getByText(/noch keine ergebnisse/i)).toBeDefined()
  })

  it('renders one card per fact-check', () => {
    const factChecks = [
      { id: 1, sprecher: 'Anna', behauptung: 'A', consistency: 'hoch', begruendung: 'x', quellen: [], status: 'done' },
      { id: 2, sprecher: 'Bert', behauptung: 'B', consistency: '', begruendung: '', quellen: [], status: 'processing' },
    ]
    render(<ResultsFeed factChecks={factChecks} onSelect={() => {}} />)
    expect(screen.getByText('Anna')).toBeDefined()
    expect(screen.getByText('Bert')).toBeDefined()
  })
})
