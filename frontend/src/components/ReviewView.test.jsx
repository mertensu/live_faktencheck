import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../services/api', () => ({
  fetchPendingClaims: vi.fn(),
  fetchFactChecks: vi.fn(),
  approveClaims: vi.fn().mockResolvedValue({}),
  discardClaims: vi.fn().mockResolvedValue({}),
  setSessionAutoCheck: vi.fn().mockResolvedValue({ auto_check: true }),
}))

import * as api from '../services/api'
import { ReviewView } from './ReviewView'

const block = (id, claims) => ({ block_id: id, timestamp: '2026-06-11T10:00:00', claims })

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchPendingClaims.mockResolvedValue([
    block('b1', [{ name: 'Anna', claim: 'A1' }, { name: 'Bert', claim: 'A2' }]),
  ])
  api.fetchFactChecks.mockResolvedValue([])
})

describe('ReviewView', () => {
  it('shows the first pending claim with a remaining counter', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    expect(await screen.findByText('Anna')).toBeDefined()
    expect(screen.getByText(/noch 2/i)).toBeDefined()
  })

  it('keep calls approveClaims and advances to the next claim', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /behalten/i }))
    await waitFor(() =>
      expect(api.approveClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
  })

  it('discard calls discardClaims and advances', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /verwerfen/i }))
    await waitFor(() =>
      expect(api.discardClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
  })

  it('toggling Auto calls setSessionAutoCheck and hides the swipe card', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('checkbox', { name: /auto-prüfung/i }))
    await waitFor(() => expect(api.setSessionAutoCheck).toHaveBeenCalledWith('s1', true))
    expect(screen.getByText(/handy kann liegen bleiben/i)).toBeDefined()
    expect(screen.queryByText('Anna')).toBeNull()
  })

  it('shows the waiting state when there are no pending claims (Auto off)', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    expect(await screen.findByText(/warte auf aussagen/i)).toBeDefined()
  })
})
