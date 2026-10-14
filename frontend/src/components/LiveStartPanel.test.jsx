import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { LiveStartPanel } from './LiveStartPanel'

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
})
