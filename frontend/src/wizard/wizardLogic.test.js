import { describe, it, expect } from 'vitest'
import {
  TYPE_LABELS, STEPS, initialWizardState, wizardReducer,
  formatParticipant, buildGuests, peopleStepValid, deriveTitle, buildSessionPayload,
} from './wizardLogic'

describe('formatParticipant', () => {
  it('debate: name + party + role', () => {
    expect(formatParticipant('debate', { name: 'Heidi Reichinnek', party: 'Linke', role: 'Fraktionsvorsitzende' }))
      .toBe('Heidi Reichinnek (Linke, Fraktionsvorsitzende)')
  })
  it('private: omits party, keeps optional role', () => {
    expect(formatParticipant('private', { name: 'Onkel Klaus', party: 'CDU', role: '' })).toBe('Onkel Klaus')
    expect(formatParticipant('private', { name: 'Klaus', party: '', role: 'Nachbar' })).toBe('Klaus (Nachbar)')
  })
  it('empty name => empty string', () => {
    expect(formatParticipant('debate', { name: '   ', party: 'X', role: 'Y' })).toBe('')
  })
})

describe('buildGuests', () => {
  it('filters out empty people', () => {
    const people = [{ name: 'A', party: '', role: '' }, { name: '', party: '', role: '' }]
    expect(buildGuests('debate', people)).toEqual(['A'])
  })
})

describe('peopleStepValid', () => {
  it('private: always valid (step may be left empty)', () => {
    expect(peopleStepValid('private', [{ name: '', party: '', role: '' }])).toBe(true)
  })
  it('debate/interview: needs at least one named person', () => {
    expect(peopleStepValid('debate', [{ name: '', party: 'SPD', role: 'X' }])).toBe(false)
    expect(peopleStepValid('debate', [{ name: '  ', party: '', role: '' }])).toBe(false)
    expect(peopleStepValid('debate', [{ name: 'Anna', party: '', role: '' }])).toBe(true)
    expect(peopleStepValid('interview', [{ name: '', party: '', role: '' }, { name: 'Bob', party: '', role: '' }])).toBe(true)
  })
})

describe('deriveTitle', () => {
  it('uses first named participant', () => {
    expect(deriveTitle('interview', [{ name: 'Robert Habeck' }])).toBe('Interview: Robert Habeck')
  })
  it('falls back to type label when nobody is named', () => {
    expect(deriveTitle('private', [{ name: '' }])).toBe('Privates Gespräch')
  })
})

describe('buildSessionPayload', () => {
  it('skipped topic => empty context; date empty', () => {
    const s = { ...initialWizardState(), conversationType: 'private',
                people: [{ name: 'Klaus', party: '', role: '' }], topic: '', title: '' }
    expect(buildSessionPayload(s)).toEqual({
      title: 'Privates Gespräch: Klaus',
      conversation_type: 'private',
      guests: ['Klaus'],
      context: '',
      date: '',
      type: 'show',
    })
  })
  it('explicit topic and edited title win', () => {
    const s = { ...initialWizardState(), conversationType: 'debate',
                people: [{ name: 'A', party: 'SPD', role: '' }], topic: 'Rente', title: 'Mein Titel' }
    const p = buildSessionPayload(s)
    expect(p.context).toBe('Rente')
    expect(p.title).toBe('Mein Titel')
    expect(p.guests).toEqual(['A (SPD)'])
  })
})

describe('wizardReducer', () => {
  it('SET_TYPE interview seeds two person slots', () => {
    const s = wizardReducer(initialWizardState(), { type: 'SET_TYPE', value: 'interview' })
    expect(s.conversationType).toBe('interview')
    expect(s.people).toHaveLength(2)
  })
  it('ADD_PERSON / REMOVE_PERSON / UPDATE_PERSON', () => {
    let s = wizardReducer(initialWizardState(), { type: 'SET_TYPE', value: 'debate' })
    s = wizardReducer(s, { type: 'ADD_PERSON' })
    expect(s.people).toHaveLength(2)
    s = wizardReducer(s, { type: 'UPDATE_PERSON', index: 0, field: 'name', value: 'Z' })
    expect(s.people[0].name).toBe('Z')
    s = wizardReducer(s, { type: 'REMOVE_PERSON', index: 1 })
    expect(s.people).toHaveLength(1)
  })
  it('NEXT/BACK clamp within STEPS bounds', () => {
    let s = initialWizardState()
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'NEXT' })
    expect(s.step).toBe(STEPS.length - 1)
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'BACK' })
    expect(s.step).toBe(0)
  })
})
