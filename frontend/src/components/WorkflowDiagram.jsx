const WAVEFORM_HEIGHTS = [28, 58, 38, 82, 48, 92, 32, 72, 52, 88, 42, 62, 36, 78]

function WaveformBars() {
  return (
    <div className="audio-waveform">
      {WAVEFORM_HEIGHTS.map((h, i) => (
        <div key={i} className="waveform-bar" style={{ height: `${h}%` }} />
      ))}
    </div>
  )
}

// The live lane streams continuously; the chunks only suggest sentences passing by.
const SENTENCES = [
  { id: 1, label: 'Satz 1', state: 'done' },
  { id: 2, label: 'Satz 2', state: 'done' },
  { id: 3, label: 'Satz 3', state: 'active' },
  { id: 4, label: '…', state: 'pending' },
]

const PIPELINE_STEPS = [
  { label: 'Transkription', sublabel: 'AssemblyAI Streaming' },
  { label: 'Satzauswahl', sublabel: 'KI-Filter: prüfbar & relevant?' },
  { label: 'Umformulierung', sublabel: 'eigenständige Aussage + Suchanfragen' },
  { label: 'Schnellcheck', sublabel: 'LLM + Websuche', search: true },
  { label: 'Darstellung', sublabel: 'markiert im Live-Transkript' },
]

function ParallelSearch() {
  return (
    <div className="react-loop">
      <div className="react-loop-steps">
        <span className="react-loop-step">Suchen ×5</span>
        <span className="react-loop-sep">→</span>
        <span className="react-loop-step">Bewerten</span>
      </div>
    </div>
  )
}

export function WorkflowDiagram() {
  return (
    <div className="workflow-diagram">
      <div className="workflow-section-label">Live-Audiosignal</div>

      <div className="workflow-audio-row">
        <div className="workflow-audio-stream">
          {SENTENCES.map((s) => (
            <div key={s.id} className={`audio-chunk audio-chunk--${s.state}`}>
              {s.state === 'active' && <span className="audio-recording-dot" />}
              <WaveformBars />
              <span className="audio-chunk-label">{s.label}</span>
            </div>
          ))}
        </div>
        <div className="audio-stream-more">→</div>
      </div>

      <div className="workflow-connector">
        <span className="workflow-connector-arrow">↓</span>
        <span className="workflow-connector-text">Satz für Satz</span>
      </div>

      <div className="workflow-pipeline">
        {PIPELINE_STEPS.map((step, i) => (
          <div key={step.label} className="pipeline-step-wrapper">
            <div className={`pipeline-step${step.search ? ' pipeline-step--react' : ''}`}>
              <div className="pipeline-step-label">{step.label}</div>
              {step.search && <ParallelSearch />}
              <div className="pipeline-step-sublabel">{step.sublabel}</div>
            </div>
            {i < PIPELINE_STEPS.length - 1 && (
              <div className="pipeline-arrow">→</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
