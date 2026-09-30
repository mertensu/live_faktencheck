import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MyChecksPage } from './MyChecksPage'

const renderPage = () => render(<MemoryRouter><MyChecksPage /></MemoryRouter>)

describe('MyChecksPage', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('asks for a code when none is stored', () => {
    renderPage()
    expect(screen.getByText(/mit einem zugangscode/i)).toBeDefined()
  })

  it('lists the own sessions with claim counts', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([
      { session_id: 's1', title: 'Hart aber fair', date: '', created_at: '2026-09-30T20:15:00', claims: 3, hoch: 2, niedrig: 1, unklar: 0 },
    ]), { status: 200, headers: { 'content-type': 'application/json' } }))
    renderPage()
    expect(await screen.findByText('Hart aber fair')).toBeDefined()
    expect(screen.getByText('3 Aussagen')).toBeDefined()
    expect(screen.getByText(/2 hoch/)).toBeDefined()
    expect(screen.queryByText(/unklar/)).toBeNull()
    expect(fetch.mock.calls[0][1].headers['X-Access-Code']).toBe('abc')
  })

  it('shows the empty state', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]', {
      status: 200, headers: { 'content-type': 'application/json' },
    }))
    renderPage()
    expect(await screen.findByText(/noch keine eigenen checks/i)).toBeDefined()
  })
})
