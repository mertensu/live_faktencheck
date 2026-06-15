// Pure, framework-free wizard logic — unit-tested in wizardLogic.test.js.

export const CONVERSATION_TYPES = ['debate', 'interview', 'private']

export const TYPE_LABELS = {
  debate: 'Öffentliche Debatte',
  interview: 'Interview',
  private: 'Privates Gespräch',
}

export const STEPS = ['type', 'people', 'topic', 'review']

const emptyPerson = () => ({ name: '', party: '', role: '', exclude: false })

export function initialWizardState() {
  return {
    step: 0,
    conversationType: null,
    people: [emptyPerson()],
    topic: '',
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

// Gating for the "people" step. Private conversations may be left empty;
// debate/interview need at least one named participant — the name is what the
// speaker-label resolver maps generic labels ("Sprecher A") onto. Party/role are
// optional but help the resolver when names aren't spoken in the transcript.
// Any participant flagged `exclude` must be named: the extractor identifies
// excluded speakers by their resolved name.
export function peopleStepValid(type, people) {
  if (people.some((p) => p.exclude && !(p.name || '').trim())) return false
  if (type === 'private') return true
  return people.some((p) => (p.name || '').trim())
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
    date: '',
    type: 'show',
    excluded_speakers: state.people
      .filter((p) => p.exclude && (p.name || '').trim())
      .map((p) => p.name.trim()),
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
