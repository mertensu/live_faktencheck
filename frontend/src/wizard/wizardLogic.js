// Pure, framework-free wizard logic — unit-tested in wizardLogic.test.js.

export const CONVERSATION_TYPES = ['debate', 'interview', 'private']

export const TYPE_LABELS = {
  debate: 'Öffentliche Debatte',
  interview: 'Interview',
  private: 'Privates Gespräch',
}

// People and topic share one page: names (party optional) and what the conversation is about.
export const STEPS = ['type', 'people', 'mode', 'review']

// `role` has no field any more (it stays empty): live, the operator assigns speakers by click.
// The party still helps ("meine Partei …" becomes checkable) and is a transcription keyterm.
const emptyPerson = () => ({ name: '', party: '', role: '', exclude: false })

export function initialWizardState() {
  return {
    step: 0,
    conversationType: null,
    people: [emptyPerson()],
    topic: '',
    // Extra names/terms for the transcription (people mentioned in the show, …), comma-separated.
    keyterms: '',
    // The user's chosen role for this session: null = not yet decided,
    // false = Moderator:in (decide each claim manually), true = automatic checking.
    autoCheck: null,
    title: '',
    titleEdited: false,
  }
}

export function formatParticipant(type, person) {
  const name = (person.name || '').trim()
  if (!name) return ''
  const parts = []
  if (type !== 'private' && (person.party || '').trim()) parts.push(person.party.trim())
  if ((person.role || '').trim()) parts.push(person.role.trim())
  return parts.length ? `${name} (${parts.join(', ')})` : name
}

export function buildGuests(type, people) {
  return people.map((p) => formatParticipant(type, p)).filter(Boolean)
}

// Gating for the "people" step. Naming is optional for every conversation type:
// the step may be left empty, and any unnamed speaker simply stays as its generic
// label ("Sprecher A/B/C") in the fact-check. Names are what the speaker-label
// resolver maps those generic labels onto; party/role further help when names
// aren't spoken in the transcript. The one hard rule: any participant flagged
// `exclude` must be named, because the extractor identifies excluded speakers by
// their resolved name.
export function peopleStepValid(type, people) {
  return !people.some((p) => p.exclude && !(p.name || '').trim())
}

// Comma- or line-separated terms → trimmed list without empties or case-insensitive repeats.
export function parseKeyterms(text) {
  const seen = new Set()
  return (text || '').split(/[,\n]/).map((t) => t.trim()).filter((t) => {
    const key = t.toLowerCase()
    if (!t || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function deriveTitle(type, people) {
  const label = TYPE_LABELS[type] || 'Gespräch'
  const firstNamed = people.map((p) => (p.name || '').trim()).find(Boolean)
  return firstNamed ? `${label}: ${firstNamed}` : label
}

export function buildSessionPayload(state) {
  const type = state.conversationType
  return {
    title: (state.title && state.title.trim()) || deriveTitle(type, state.people),
    conversation_type: type,
    guests: buildGuests(type, state.people),
    context: state.topic.trim(),
    keyterms: parseKeyterms(state.keyterms),
    date: '',
    type: 'show',
    excluded_speakers: state.people
      .filter((p) => p.exclude && (p.name || '').trim())
      .map((p) => p.name.trim()),
    auto_check: !!state.autoCheck,
  }
}

export function wizardReducer(state, action) {
  switch (action.type) {
    case 'SET_TYPE': {
      const people = action.value === 'interview'
        ? [emptyPerson(), emptyPerson()]
        : [emptyPerson()]
      return { ...state, conversationType: action.value, people }
    }
    case 'ADD_PERSON':
      return { ...state, people: [...state.people, emptyPerson()] }
    case 'REMOVE_PERSON':
      return { ...state, people: state.people.filter((_, i) => i !== action.index) }
    case 'UPDATE_PERSON':
      return {
        ...state,
        people: state.people.map((p, i) =>
          i === action.index ? { ...p, [action.field]: action.value } : p),
      }
    case 'SET_TOPIC':
      return { ...state, topic: action.value }
    case 'SET_KEYTERMS':
      return { ...state, keyterms: action.value }
    case 'SET_AUTO_CHECK':
      return { ...state, autoCheck: action.value }
    case 'SET_TITLE':
      return { ...state, title: action.value, titleEdited: true }
    case 'NEXT':
      return { ...state, step: Math.min(state.step + 1, STEPS.length - 1) }
    case 'BACK':
      return { ...state, step: Math.max(state.step - 1, 0) }
    default:
      return state
  }
}
