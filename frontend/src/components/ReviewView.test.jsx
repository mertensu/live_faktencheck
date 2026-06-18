import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../services/api', () => ({
  fetchPendingClaims: vi.fn(),
  fetchFactChecks: vi.fn(),
  fetchDiscardedClaims: vi.fn(),
  fetchPipelineStatus: vi.fn(),
  approveClaims: vi.fn().mockResolvedValue({}),
  discardClaims: vi.fn().mockResolvedValue({}),
  setSessionAutoCheck: vi.fn().mockResolvedValue({ auto_check: true }),
}))

import * as api from '../services/api'
import { ReviewView } from './ReviewView'

const block = (id, claims) => ({ block_id: id, timestamp: '2026-06-11T10:00:00', claims })

beforeEach(() => {
  vi.clearAllMocks()
  // jsdom has no matchMedia; SpeakerColumns (read-only view) uses it for responsiveness.
  window.matchMedia = window.matchMedia || ((query) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }))
  api.fetchPendingClaims.mockResolvedValue([
    block('b1', [{ name: 'Anna', claim: 'A1' }, { name: 'Bert', claim: 'A2' }]),
  ])
  api.fetchFactChecks.mockResolvedValue([])
  api.fetchDiscardedClaims.mockResolvedValue([])
  api.fetchPipelineStatus.mockResolvedValue([])
})

describe('ReviewView', () => {
  it('shows the first pending claim with a remaining counter', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    expect(await screen.findByText('Anna')).toBeDefined()
    expect(screen.getByText(/noch 2/i)).toBeDefined()
  })

  it('keep calls approveClaims, advances, and the decided claim does not reappear', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /behalten/i }))
    await waitFor(() =>
      expect(api.approveClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
    // The backend never removes the claim from pending-claims; it must not come
    // back nor stay actionable once decided.
    expect(screen.queryByText('Anna')).toBeNull()
  })

  it('discard calls discardClaims, advances, and the decided claim does not reappear', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /verwerfen/i }))
    await waitFor(() =>
      expect(api.discardClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
    expect(screen.queryByText('Anna')).toBeNull()
  })

  it('toggling Auto calls setSessionAutoCheck and hides the swipe card', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('checkbox', { name: /auto-prüfung/i }))
    await waitFor(() => expect(api.setSessionAutoCheck).toHaveBeenCalledWith('s1', true))
    expect(screen.getByText(/handy kann liegen bleiben/i)).toBeDefined()
    expect(screen.queryByText('Anna')).toBeNull()
  })

  it('hides the swipe card when the auto flag arrives after mount (async config load)', async () => {
    // Reproduces the real bug: the session is in auto mode, but the parent only
    // learns auto_check=true after the async config fetch resolves, so ReviewView
    // first mounts with initialAutoCheck={false} and then re-renders with {true}.
    // The swipe card must follow the prop, not stay stuck on its mount value.
    const { rerender } = render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')  // swipe card is showing (Auto off)

    rerender(<ReviewView sessionId="s1" initialAutoCheck={true} />)

    expect(await screen.findByText(/handy kann liegen bleiben/i)).toBeDefined()
    expect(screen.queryByText('Anna')).toBeNull()
    expect(screen.getByRole('checkbox', { name: /auto-prüfung/i }).checked).toBe(true)
  })

  it('shows the start screen (start button) when idle and empty, and starts recording on click', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    const onStartRecording = vi.fn()
    render(
      <ReviewView
        sessionId="s1"
        initialAutoCheck={false}
        isRecording={false}
        onStartRecording={onStartRecording}
      />
    )
    const btn = await screen.findByRole('button', { name: /aufnahme starten/i })
    // The Auto toggle is hidden on the start screen ("sonst nichts").
    expect(screen.queryByRole('checkbox', { name: /auto-prüfung/i })).toBeNull()
    fireEvent.click(btn)
    expect(onStartRecording).toHaveBeenCalled()
  })

  it('still shows the big start button before the first recording when Auto was chosen upfront', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    const onStartRecording = vi.fn()
    render(
      <ReviewView
        sessionId="s1"
        initialAutoCheck={true}
        isRecording={false}
        onStartRecording={onStartRecording}
      />
    )
    const btn = await screen.findByRole('button', { name: /aufnahme starten/i })
    fireEvent.click(btn)
    expect(onStartRecording).toHaveBeenCalled()
  })

  it('shows "Noch keine Behauptungen" while recording with no pending claims (Auto off)', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} isRecording={true} />)
    expect(await screen.findByText(/noch keine behauptungen/i)).toBeDefined()
  })

  it('shows the extraction status when a block of this session is mid-pipeline', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    api.fetchPipelineStatus.mockResolvedValue([
      { block_id: 'blk1', session_id: 's1', status: 'processing' },
      { block_id: 'other', session_id: 'someone-else', status: 'processing' },
    ])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} isRecording={true} />)
    expect(await screen.findByText(/behauptungen werden extrahiert/i)).toBeDefined()
  })

  it('reports a completed 0-claim block ("Keine Behauptungen in diesem Abschnitt gefunden")', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    api.fetchPipelineStatus.mockResolvedValue([
      { block_id: 'blk1', session_id: 's1', status: 'done', started_at: '2026-06-12T10:00:00Z', claim_count: 0 },
    ])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} isRecording={true} />)
    expect(await screen.findByText(/keine behauptungen in diesem abschnitt gefunden/i)).toBeDefined()
  })

  it('does not report 0-claim when the most recent completed block had claims', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    api.fetchPipelineStatus.mockResolvedValue([
      { block_id: 'blk1', session_id: 's1', status: 'done', started_at: '2026-06-12T10:00:00Z', claim_count: 0 },
      { block_id: 'blk2', session_id: 's1', status: 'done', started_at: '2026-06-12T10:01:00Z', claim_count: 2 },
    ])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} isRecording={true} />)
    expect(await screen.findByText(/noch keine behauptungen/i)).toBeDefined()
    expect(screen.queryByText(/in diesem abschnitt/i)).toBeNull()
  })

  it('keeps already-decided claims out of the queue (seeded from backend records)', async () => {
    // Anna already approved (fact-check exists), Bert already discarded — neither
    // should appear even though both are still in the pending store. This is the
    // state after a Review -> Pro -> Review round-trip (in-memory handled lost).
    api.fetchPendingClaims.mockResolvedValue([
      block('b1', [
        { name: 'Anna', claim: 'A1' },
        { name: 'Bert', claim: 'A2' },
        { name: 'Cara', claim: 'A3' },
      ]),
    ])
    api.fetchFactChecks.mockResolvedValue([
      { id: 1, sprecher: 'Anna', behauptung: 'A1', status: 'done' },
    ])
    api.fetchDiscardedClaims.mockResolvedValue([
      { id: 2, sprecher: 'Bert', behauptung: 'A2', status: 'discarded' },
    ])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} isRecording={true} />)
    // Only the undecided claim (Cara) is offered.
    expect(await screen.findByText('Cara')).toBeDefined()
    expect(screen.queryByText('Bert')).toBeNull()
    expect(screen.getByText(/noch 1/i)).toBeDefined()
  })

  it('shows a read-only speaker-column view for a past example episode', async () => {
    // Opening a "Beispiel" episode: no pending claims, never recorded this load,
    // but the session already has fact-checks in the DB. Show finished results
    // grouped by speaker — not the swipe queue, the Auto toggle, or the splash.
    api.fetchPendingClaims.mockResolvedValue([])
    api.fetchFactChecks.mockResolvedValue([
      { id: 1, sprecher: 'Anna', behauptung: 'A1', consistency: 'hoch', status: 'done', timestamp: '2026-03-26T20:00:00Z' },
      { id: 2, sprecher: 'Bert', behauptung: 'B1', consistency: 'niedrig', status: 'done', timestamp: '2026-03-26T20:01:00Z' },
    ])
    render(
      <ReviewView
        sessionId="maischberger"
        initialAutoCheck={false}
        isRecording={false}
        everRecorded={false}
      />
    )
    // Speaker column headers and their claims render.
    expect(await screen.findByText('Anna')).toBeDefined()
    expect(screen.getByText('Bert')).toBeDefined()
    expect(screen.getByText('A1')).toBeDefined()
    expect(screen.getByText('B1')).toBeDefined()
    // No onboarding splash, no Auto toggle, no swipe-stage placeholder.
    expect(screen.queryByRole('button', { name: /aufnahme starten/i })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: /auto-prüfung/i })).toBeNull()
    expect(screen.queryByText(/noch keine behauptungen/i)).toBeNull()
  })

  it('does not return to the start screen after recording has happened (stopped, empty)', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    render(
      <ReviewView
        sessionId="s1"
        initialAutoCheck={false}
        isRecording={false}
        everRecorded={true}
      />
    )
    // Neutral empty state, NOT the splash start button.
    expect(await screen.findByText(/noch keine behauptungen/i)).toBeDefined()
    expect(screen.queryByRole('button', { name: /aufnahme starten/i })).toBeNull()
  })
})
