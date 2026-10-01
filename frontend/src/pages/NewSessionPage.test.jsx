import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NewSessionPage } from './NewSessionPage'

describe('NewSessionPage', () => {
  it('asks one thing per page: speakers, topic, names & terms, then the overview', () => {
    render(<MemoryRouter><NewSessionPage /></MemoryRouter>)
    const next = () => fireEvent.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(screen.queryByText('Was für ein Gespräch?')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Wer spricht?' })).toBeDefined()
    expect(screen.getAllByPlaceholderText('Partei / Organisation (optional)')).toHaveLength(2)
    expect(screen.queryByPlaceholderText(/Rolle/)).toBeNull()
    expect(screen.queryByPlaceholderText(/Anlass, Ort\/Zeitraum/)).toBeNull()
    next()
    expect(screen.getByRole('heading', { name: /Worum geht es\?/ })).toBeDefined()
    expect(screen.getByPlaceholderText(/Anlass, Ort\/Zeitraum/)).toBeDefined()
    next()
    expect(screen.getByLabelText(/Namen & Begriffe/)).toBeDefined()
    next()
    expect(screen.getByRole('heading', { name: 'Übersicht' })).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Zurück' }))
    expect(screen.getByLabelText(/Namen & Begriffe/)).toBeDefined()
  })
})
