import { describe, it, expect } from 'vitest'
import { turnLines, placeTurn, assignFrom, nameAt, audioConstraints } from './useAudioStream'

describe('turn lines', () => {
  const msg = {
    turn_order: 3, label: 'A', text: 'Ist das falsch? Also nein.',
    segments: [{ label: 'C', text: 'Ist das falsch?' }, { label: 'A', text: 'Also nein.' }],
  }

  it('makes one line per speaker segment', () => {
    expect(turnLines(msg)).toEqual([
      { label: 'C', text: 'Ist das falsch?', turnOrder: 3 },
      { label: 'A', text: 'Also nein.', turnOrder: 3 },
    ])
    expect(turnLines({ turn_order: 1, label: 'B', text: 'Ja.' })).toEqual([{ label: 'B', text: 'Ja.', turnOrder: 1 }])
  })

  it('appends a new turn and replaces a re-sent one in place', () => {
    const before = [{ label: 'B', text: 'Vorher.', turnOrder: 2 }]
    const once = placeTurn(before, 3, turnLines(msg), true)
    expect(once).toHaveLength(3)
    const after = [...once, { label: 'B', text: 'Danach.', turnOrder: 4 }]
    const resplit = placeTurn(after, 3, [{ label: 'A', text: 'Ist das falsch? Also nein.', turnOrder: 3 }], true)
    expect(resplit.map((t) => t.text)).toEqual(['Vorher.', 'Ist das falsch? Also nein.', 'Danach.'])
  })

  it('leaves a turn the operator split by hand alone', () => {
    const split = [{ label: 'A', text: 'Ist das falsch?', turnOrder: 3, speaker: 'Maischberger' },
      { label: 'A', text: 'Also nein.', turnOrder: 3 }]
    expect(placeTurn(split, 3, turnLines(msg), true)).toBe(split)
  })
})

describe('speaker names from a turn on', () => {
  it('keeps earlier turns and replaces what comes later', () => {
    let map = assignFrom({}, 'B', 3, 'Maischberger')
    map = assignFrom(map, 'B', 5, 'Connemann')
    expect(nameAt(map, 'B', 2)).toBeNull()
    expect(nameAt(map, 'B', 4)).toBe('Maischberger')
    expect(nameAt(map, 'B', 9)).toBe('Connemann')
    expect(nameAt(map, 'B', null)).toBe('Connemann')
    // A click on the first bubble corrects everything from there on.
    map = assignFrom(map, 'B', 3, 'Dröge')
    expect(map.B).toEqual([[3, 'Dröge']])
    expect(nameAt(assignFrom(map, 'B', null, null), 'B', 9)).toBeNull()
  })
})

describe('audio constraints', () => {
  const raw = { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
  it('turns the browser call-processing off for the default input', () => {
    expect(audioConstraints('')).toEqual({ audio: raw })
  })
  it('keeps it off for a chosen input', () => {
    expect(audioConstraints('mic-2')).toEqual({ audio: { ...raw, deviceId: { exact: 'mic-2' } } })
  })
})
