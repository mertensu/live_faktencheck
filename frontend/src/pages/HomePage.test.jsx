import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { HomePage } from './HomePage'

const renderHome = () => render(
  <MemoryRouter initialEntries={['/']}>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/mein-bereich" element={<p>Mein Bereich geöffnet</p>} />
    </Routes>
  </MemoryRouter>
)

describe('HomePage "Jetzt starten"', () => {
  beforeEach(() => localStorage.clear())

  it('asks for a code when none is stored', () => {
    renderHome()
    expect(screen.queryByLabelText('Zugangscode')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /jetzt starten/i }))
    expect(screen.getByLabelText('Zugangscode')).toBeDefined()
  })

  it('goes straight into "Mein Bereich" with a stored code', () => {
    localStorage.setItem('fc_access_code', 'abc')
    renderHome()
    fireEvent.click(screen.getByRole('button', { name: /jetzt starten/i }))
    expect(screen.getByText('Mein Bereich geöffnet')).toBeDefined()
  })
})
