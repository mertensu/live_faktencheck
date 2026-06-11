import { useReducer, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, getAccessCode, setAccessCode } from '../services/api'
import {
  TYPE_LABELS, STEPS, initialWizardState, wizardReducer, buildSessionPayload, peopleStepValid,
} from '../wizard/wizardLogic'

const TYPE_TILES = [
  { value: 'debate', icon: '🏛️', label: 'Öffentliche Debatte / Talkshow' },
  { value: 'interview', icon: '🎙️', label: 'Interview' },
  { value: 'private', icon: '💬', label: 'Privates Gespräch' },
]

function PersonFields({ person, index, type, dispatch, removable }) {
  const upd = (field) => (e) =>
    dispatch({ type: 'UPDATE_PERSON', index, field, value: e.target.value })
  return (
    <div className="wizard-person">
      <input className="wizard-input" value={person.name} onChange={upd('name')}
             placeholder="Name" />
      {type !== 'private' && (
        <input className="wizard-input" value={person.party} onChange={upd('party')}
               placeholder="Partei / Organisation" />
      )}
      <input className="wizard-input" value={person.role} onChange={upd('role')}
             placeholder={type === 'private' ? 'Rolle (optional, z. B. Nachbar)' : 'Rolle / Funktion'} />
      {removable && (
        <button type="button" className="wizard-remove"
                onClick={() => dispatch({ type: 'REMOVE_PERSON', index })}>Entfernen</button>
      )}
    </div>
  )
}

export function NewSessionPage() {
  const navigate = useNavigate()
  const [state, dispatch] = useReducer(wizardReducer, undefined, initialWizardState)
  const [accessCode, setAccessCodeInput] = useState(getAccessCode())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const needsCode = !getAccessCode()
  const stepName = STEPS[state.step]

  const canAdvance = () => {
    if (stepName === 'type') return !!state.conversationType
    if (stepName === 'people') return peopleStepValid(state.conversationType, state.people)
    return true
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    if (accessCode) setAccessCode(accessCode.trim())
    try {
      const result = await createSession(buildSessionPayload(state))
      if (!result?.session_id) throw new Error('Keine Session-ID erhalten')
      navigate('/' + result.session_id)
    } catch (err) {
      const msg = err.message || 'Fehler beim Erstellen der Session'
      if (/401|403|Zugangscode/i.test(msg)) setAccessCode('')
      setError(msg)
      setSubmitting(false)
    }
  }

  return (
    <div className="about-page">
      <div className="about-content wizard">
        <div className="wizard-progress">
          {STEPS.map((s, i) => (
            <span key={s} className={`wizard-dot ${i === state.step ? 'active' : ''} ${i < state.step ? 'done' : ''}`} />
          ))}
        </div>

        {stepName === 'type' && (
          <section className="wizard-step">
            <h1>Was für ein Gespräch?</h1>
            <div className="wizard-tiles">
              {TYPE_TILES.map((t) => (
                <button key={t.value} type="button"
                        className={`wizard-tile ${state.conversationType === t.value ? 'selected' : ''}`}
                        onClick={() => dispatch({ type: 'SET_TYPE', value: t.value })}>
                  <span className="wizard-tile-icon">{t.icon}</span>
                  <span>{t.label}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {stepName === 'people' && (
          <section className="wizard-step">
            <h1>Wer spricht?</h1>
            {state.conversationType === 'interview' && (
              <p className="wizard-hint">Erste Person = interviewt, zweite = interviewende Person/Medium (optional).</p>
            )}
            {state.conversationType === 'private' && (
              <p className="wizard-hint">Nur Vornamen/Rollen genügen — keine Partei nötig. Du kannst diesen Schritt auch leer lassen.</p>
            )}
            {state.conversationType !== 'private' && (
              <p className="wizard-hint">
                Mindestens ein <strong>Name</strong> ist nötig – darauf ordnet die KI die Sprecher zu.
                Partei/Organisation und Rolle sind optional, verbessern aber die Zuordnung, wenn Namen im Gespräch nicht fallen.
              </p>
            )}
            {state.people.map((p, i) => (
              <PersonFields key={i} person={p} index={i} type={state.conversationType}
                            dispatch={dispatch}
                            removable={state.conversationType !== 'interview' && state.people.length > 1} />
            ))}
            {state.conversationType !== 'interview' && (
              <button type="button" className="wizard-add"
                      onClick={() => dispatch({ type: 'ADD_PERSON' })}>+ weitere Person</button>
            )}
          </section>
        )}

        {stepName === 'topic' && (
          <section className="wizard-step">
            <h1>Worum geht es? <span className="wizard-optional">(optional)</span></h1>
            <textarea className="wizard-input" rows={4} value={state.topic}
                      onChange={(e) => dispatch({ type: 'SET_TOPIC', value: e.target.value })}
                      placeholder="Thema / Hintergrund — kann leer bleiben" />
          </section>
        )}

        {stepName === 'review' && (
          <section className="wizard-step">
            <h1>Übersicht</h1>
            <dl className="wizard-summary">
              <dt>Art</dt><dd>{TYPE_LABELS[state.conversationType]}</dd>
              <dt>Personen</dt><dd>{buildSessionPayload(state).guests.join(', ') || '—'}</dd>
              <dt>Thema</dt><dd>{state.topic.trim() || '— (nicht angegeben)'}</dd>
            </dl>
            <div className="form-field">
              <label htmlFor="wizard-title">Titel</label>
              <input id="wizard-title" className="wizard-input"
                     value={state.titleEdited ? state.title : buildSessionPayload(state).title}
                     onChange={(e) => dispatch({ type: 'SET_TITLE', value: e.target.value })} />
            </div>
            {needsCode && (
              <div className="form-field">
                <label htmlFor="wizard-code">Zugangscode</label>
                <input id="wizard-code" type="password" className="wizard-input" autoComplete="off"
                       value={accessCode} onChange={(e) => setAccessCodeInput(e.target.value)}
                       placeholder="Dein persönlicher Zugangscode" />
              </div>
            )}
            {error && <p className="form-error">{error}</p>}
          </section>
        )}

        <div className="wizard-nav">
          {state.step > 0 && (
            <button type="button" className="action-button"
                    onClick={() => dispatch({ type: 'BACK' })} disabled={submitting}>Zurück</button>
          )}
          {stepName !== 'review' ? (
            <button type="button" className="action-button primary"
                    onClick={() => dispatch({ type: 'NEXT' })} disabled={!canAdvance()}>Weiter</button>
          ) : (
            <button type="button" className="action-button primary"
                    onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Wird erstellt...' : 'Session erstellen'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
