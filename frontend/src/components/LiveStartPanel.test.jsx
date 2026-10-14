import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { LiveStartPanel, LiveStartDesktopOnly, isTouchOnly } from './LiveStartPanel'

const mic = (devices = []) => ({
  devices, deviceId: '', setDeviceId: vi.fn(), listDevices: vi.fn(),
})

function renderPanel(props = {}) {
  return render(
    <LiveStartPanel
      sessionId="abc123"
      mic={mic()}
      speakers={['Markus Söder', 'Jessy Wellmer']}
      excludedSpeakers={['Jessy Wellmer']}
      onStart={vi.fn()}
      connecting={false}
      error={null}
      {...props}
    />,
  )
}

describe('LiveStartPanel', () => {
  beforeEach(() => {
    // No getUserMedia: the level meter stays off, as before mic permission.
    global.navigator.mediaDevices = { enumerateDevices: vi.fn(() => Promise.resolve([])) }
  })

  it('marks who is checked and who is not', () => {
    renderPanel()
    expect(screen.getByText('Markus Söder · wird geprüft')).toBeTruthy()
    expect(screen.getByText('Jessy Wellmer · nicht geprüft')).toBeTruthy()
  })

  it('says how voices show when no people were given', () => {
    renderPanel({ speakers: [], excludedSpeakers: [] })
    expect(screen.getByText(/Sprecher A, B, C/)).toBeTruthy()
  })

  it('ticks the link step once the link is copied', async () => {
    navigator.clipboard = { writeText: vi.fn(() => Promise.resolve()) }
    const { container } = renderPanel()
    expect(container.querySelectorAll('.live-start-mark--done')).toHaveLength(1)  // people only
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Live-Link kopieren/ })) })
    expect(container.querySelectorAll('.live-start-mark--done')).toHaveLength(2)
  })

  it('folds the practice open and closed', () => {
    const onPracticeOpen = vi.fn()
    const { rerender } = renderPanel({ practiceOpen: false, onPracticeOpen })
    expect(screen.queryByRole('tablist', { name: 'Übungsschritte' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Bedienung üben/ }))
    expect(onPracticeOpen).toHaveBeenCalledWith(true)
    rerender(
      <LiveStartPanel sessionId="abc123" mic={mic()} speakers={[]} excludedSpeakers={[]}
        onStart={vi.fn()} connecting={false} error={null} practiceOpen onPracticeOpen={onPracticeOpen} />,
    )
    expect(screen.getByRole('tablist', { name: 'Übungsschritte' })).toBeTruthy()
  })

  it('starts the live check from the panel', () => {
    const onStart = vi.fn()
    renderPanel({ onStart })
    fireEvent.click(screen.getByRole('button', { name: /Live-Check starten/ }))
    expect(onStart).toHaveBeenCalledOnce()
  })

  it('shows the start error in place of the note', () => {
    renderPanel({ error: 'Mikrofonzugriff verweigert' })
    expect(screen.getByRole('alert').textContent).toBe('Mikrofonzugriff verweigert')
    expect(screen.queryByText(/Stoppen jederzeit/)).toBeNull()
  })

  it('asks to load the mics before it can check the sound', () => {
    renderPanel()
    expect(screen.getByText(/Mikrofone laden, um den Ton zu prüfen/)).toBeTruthy()
  })

  it('sends phones to a computer, with the link to take along', () => {
    render(<LiveStartDesktopOnly sessionId="abc123" />)
    expect(screen.getByRole('heading', { name: /am Computer starten/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Live-Link kopieren/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Live-Check starten/ })).toBeNull()
  })
})

describe('isTouchOnly', () => {
  const media = (coarse, fine) => (q) => ({ matches: q === '(pointer: coarse)' ? coarse : q === '(any-pointer: fine)' ? fine : false })
  afterEach(() => { delete window.matchMedia })

  it('is true for a phone (coarse pointer, no fine one)', () => {
    window.matchMedia = media(true, false)
    expect(isTouchOnly()).toBe(true)
  })

  it('is false for a touch laptop or a tablet with a trackpad', () => {
    window.matchMedia = media(true, true)
    expect(isTouchOnly()).toBe(false)
  })

  it('is false without matchMedia', () => {
    expect(isTouchOnly()).toBe(false)
  })
})
