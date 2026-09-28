import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NewSessionPage } from './NewSessionPage'

describe('NewSessionPage', () => {
  it('asks for people and topic on one page, without a role field', () => {
    render(<MemoryRouter><NewSessionPage /></MemoryRouter>)
    fireEvent.click(screen.getByText('Öffentliche Debatte / Talkshow'))
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(screen.getByRole('heading', { name: 'Wer spricht und worum geht es?' })).toBeDefined()
    expect(screen.getByPlaceholderText('Partei / Organisation (optional)')).toBeDefined()
    expect(screen.queryByPlaceholderText(/Rolle/)).toBeNull()
    expect(screen.getByPlaceholderText(/Anlass, Ort\/Zeitraum/)).toBeDefined()
    expect(screen.getByLabelText(/Namen & Begriffe/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(screen.getByRole('heading', { name: 'Welche Rolle nimmst du ein?' })).toBeDefined()
  })
})
