import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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
