import { describe, it, expect } from 'vitest'
import {
  STEPS, initialWizardState, wizardReducer,
  formatParticipant, buildGuests, peopleStepValid, deriveTitle, buildSessionPayload, parseKeyterms,
} from './wizardLogic'

describe('formatParticipant', () => {
  it('name + party + role', () => {
    expect(formatParticipant({ name: 'Heidi Reichinnek', party: 'Linke', role: 'Fraktionsvorsitzende' }))
      .toBe('Heidi Reichinnek (Linke, Fraktionsvorsitzende)')
  })
  it('party and role are optional', () => {
    expect(formatParticipant({ name: 'Onkel Klaus', party: '', role: '' })).toBe('Onkel Klaus')
    expect(formatParticipant({ name: 'Klaus', party: '', role: 'Nachbar' })).toBe('Klaus (Nachbar)')
  })
  it('empty name => empty string', () => {
    expect(formatParticipant({ name: '   ', party: 'X', role: 'Y' })).toBe('')
  })
})

describe('buildGuests', () => {
  it('filters out empty people', () => {
    const people = [{ name: 'A', party: '', role: '' }, { name: '', party: '', role: '' }]
    expect(buildGuests(people)).toEqual(['A'])
  })
})

describe('peopleStepValid', () => {
  it('naming is optional (unnamed speakers stay Sprecher A/B/C)', () => {
    expect(peopleStepValid([{ name: '', party: 'SPD', role: 'X' }])).toBe(true)
    expect(peopleStepValid([{ name: '  ', party: '', role: '' }])).toBe(true)
    expect(peopleStepValid([{ name: 'Anna', party: '', role: '' }])).toBe(true)
    expect(peopleStepValid([{ name: '', party: '', role: '' }, { name: 'Bob', party: '', role: '' }])).toBe(true)
  })
})

describe('deriveTitle', () => {
  it('uses first named participant', () => {
    expect(deriveTitle([{ name: '' }, { name: 'Robert Habeck' }])).toBe('Gespräch: Robert Habeck')
  })
  it('falls back to a generic title when nobody is named', () => {
    expect(deriveTitle([{ name: '' }])).toBe('Gespräch')
  })
})

describe('buildSessionPayload', () => {
  it('skipped topic => empty context; date empty', () => {
    const s = { ...initialWizardState(),
                people: [{ name: 'Klaus', party: '', role: '' }], topic: '', title: '' }
    expect(buildSessionPayload(s)).toEqual({
      title: 'Gespräch: Klaus',
      guests: ['Klaus'],
      context: '',
      keyterms: [],
      date: '',
      type: 'show',
      excluded_speakers: [],
      auto_check: false,
    })
  })

  it('turns the comma-separated terms into a clean list', () => {
    const s = { ...initialWizardState(), people: [{ name: 'A', party: '', role: '' }],
                keyterms: ' Katharina Reiche, , Peter Altmaier\nkatharina reiche ' }
    expect(buildSessionPayload(s).keyterms).toEqual(['Katharina Reiche', 'Peter Altmaier'])
    expect(parseKeyterms('')).toEqual([])
  })
  it('explicit topic and edited title win', () => {
    const s = { ...initialWizardState(),
                people: [{ name: 'A', party: 'SPD', role: '' }], topic: 'Rente', title: 'Mein Titel' }
    const p = buildSessionPayload(s)
    expect(p.context).toBe('Rente')
    expect(p.title).toBe('Mein Titel')
    expect(p.guests).toEqual(['A (SPD)'])
  })

  it('defaults auto_check to false and reflects an explicit automatic choice', () => {
    const base = { ...initialWizardState(),
                   people: [{ name: 'A', party: '', role: '' }], topic: '', title: '' }
    expect(buildSessionPayload(base).auto_check).toBe(false)
    expect(buildSessionPayload({ ...base, autoCheck: true }).auto_check).toBe(true)
  })

  it('emits excluded_speakers from checked, named people', () => {
    const s = {
      topic: '', title: '', titleEdited: false,
      people: [
        { name: 'Caren Miosga', party: '', role: 'Moderatorin', exclude: true },
        { name: 'Heidi Reichinnek', party: 'Linke', role: '', exclude: false },
      ],
    }
    expect(buildSessionPayload(s).excluded_speakers).toEqual(['Caren Miosga'])
  })

  it('omits unchecked and unnamed people from excluded_speakers', () => {
    const s = {
      topic: '', title: '', titleEdited: false,
      people: [
        { name: '   ', party: '', role: '', exclude: true },
        { name: 'Anna', party: '', role: '', exclude: false },
      ],
    }
    expect(buildSessionPayload(s).excluded_speakers).toEqual([])
  })
})

describe('peopleStepValid with exclude', () => {
  it('false when a person is exclude-checked but unnamed ', () => {
    expect(peopleStepValid([
      { name: 'Anna', party: '', role: '', exclude: false },
      { name: '', party: '', role: '', exclude: true },
    ])).toBe(false)
  })
  it('false when an exclude-checked person is unnamed', () => {
    expect(peopleStepValid([
      { name: '', party: '', role: '', exclude: true },
    ])).toBe(false)
  })
  it('true when exclude-checked people are all named', () => {
    expect(peopleStepValid([
      { name: 'Caren Miosga', party: '', role: '', exclude: true },
    ])).toBe(true)
  })
})

describe('wizardReducer', () => {
  it('starts with two person slots', () => {
    expect(initialWizardState().people).toHaveLength(2)
  })
  it('ADD_PERSON / REMOVE_PERSON / UPDATE_PERSON', () => {
    let s = wizardReducer(initialWizardState(), { type: 'ADD_PERSON' })
    expect(s.people).toHaveLength(3)
    s = wizardReducer(s, { type: 'UPDATE_PERSON', index: 0, field: 'name', value: 'Z' })
    expect(s.people[0].name).toBe('Z')
    s = wizardReducer(s, { type: 'REMOVE_PERSON', index: 1 })
    expect(s.people).toHaveLength(2)
  })
  it('SET_AUTO_CHECK records the chosen role', () => {
    let s = wizardReducer(initialWizardState(), { type: 'SET_AUTO_CHECK', value: true })
    expect(s.autoCheck).toBe(true)
    s = wizardReducer(s, { type: 'SET_AUTO_CHECK', value: false })
    expect(s.autoCheck).toBe(false)
  })
  it('NEXT/BACK clamp within STEPS bounds', () => {
    let s = initialWizardState()
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'NEXT' })
    expect(s.step).toBe(STEPS.length - 1)
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'BACK' })
    expect(s.step).toBe(0)
  })
})
