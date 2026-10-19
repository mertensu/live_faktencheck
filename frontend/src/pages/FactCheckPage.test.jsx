import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FactCheckPage } from './FactCheckPage'

const CHECK = { id: 1, sprecher: 'Dröge', behauptung: 'Eine Aussage.', consistency: 'hoch', status: '',
  timestamp: '2026-10-16T15:40:00', quellen: [] }

function json(body) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

describe('FactCheckPage: resuming a session with results', () => {
  beforeEach(() => {
    localStorage.setItem('fc_access_code', 'abc') // operator, not viewer
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
    window.scrollTo = () => {}
    global.navigator.mediaDevices = { enumerateDevices: vi.fn(() => Promise.resolve([])) }
    global.fetch = vi.fn((url) => json(String(url).includes('/api/config/')
      ? { speakers: ['Dröge', 'Connemann'], show_name: 'Gespräch' }
      : [CHECK]))
  })
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('switches between results and the setup (source pick), starting only from the setup', async () => {
    render(<FactCheckPage showName="Gespräch" episodeKey="s1" />)
    expect(await screen.findByText('Eine Aussage.')).toBeDefined()

    expect(screen.getByRole('radio', { name: 'Ergebnisse' }).getAttribute('aria-checked')).toBe('true')
    expect(screen.queryByRole('button', { name: /Live-Check$/ })).toBeNull() // no start without the setup

    fireEvent.click(screen.getByRole('radio', { name: 'Setup' }))
    expect(screen.getByRole('region', { name: 'Live-Check vorbereiten' })).toBeDefined()
    expect(screen.queryByText('Eine Aussage.')).toBeNull()
    expect(screen.getByRole('button', { name: /Live-Check starten/ })).toBeDefined()
    expect(screen.getByRole('radio', { name: 'Setup' }).getAttribute('aria-checked')).toBe('true')

    fireEvent.click(screen.getByRole('radio', { name: 'Ergebnisse' }))
    expect(screen.getByText('Eine Aussage.')).toBeDefined()
    expect(screen.queryByRole('region', { name: 'Live-Check vorbereiten' })).toBeNull()
  })
})

describe('FactCheckPage: a Beispiel opened by an operator', () => {
  beforeEach(() => {
    localStorage.setItem('fc_access_code', 'abc')
    global.fetch = vi.fn((url) => json(String(url).includes('/api/config/')
      ? { speakers: ['Dröge'], show_name: 'Maischberger' }
      : [CHECK]))
  })
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('shows the results as every visitor sees them, without live controls', async () => {
    render(<FactCheckPage showName="Maischberger" episodeKey="s1" asViewer />)
    expect(await screen.findByText('Eine Aussage.')).toBeDefined()
    expect(screen.queryByRole('radio', { name: 'Setup' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Kurzanleitung' })).toBeNull()
  })
})
