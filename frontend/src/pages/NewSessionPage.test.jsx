import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NewSessionPage } from './NewSessionPage'

describe('NewSessionPage', () => {
  it('opens directly on people and topic, without a type or role field', () => {
    render(<MemoryRouter><NewSessionPage /></MemoryRouter>)
    expect(screen.queryByText('Was für ein Gespräch?')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Wer spricht und worum geht es?' })).toBeDefined()
    expect(screen.getAllByPlaceholderText('Partei / Organisation (optional)')).toHaveLength(2)
    expect(screen.queryByPlaceholderText(/Rolle/)).toBeNull()
    expect(screen.getByPlaceholderText(/Anlass, Ort\/Zeitraum/)).toBeDefined()
    expect(screen.getByLabelText(/Namen & Begriffe/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(screen.getByRole('heading', { name: 'Welche Rolle nimmst du ein?' })).toBeDefined()
  })
})
