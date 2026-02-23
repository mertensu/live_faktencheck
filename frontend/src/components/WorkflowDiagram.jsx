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

const CHUNKS = [
  { id: 1, label: 'Block 1', state: 'active' },
  { id: 2, label: 'Block 2', state: 'pending' },
  { id: 3, label: 'Block 3', state: 'pending' },
  { id: 4, label: 'Block 4', state: 'pending' },
]

const PIPELINE_STEPS = [
  { label: 'Transkription', sublabel: 'AssemblyAI' },
  { label: 'Claim-Extraktion', sublabel: 'LLM' },
  { label: 'Human-in-the-Loop', sublabel: 'prüfen / verwerfen' },
  { label: 'Faktencheck', sublabel: 'LLM + Websuche', react: true },
  { label: 'Darstellung', sublabel: 'Begründung + Quellen' },
]

function ReActLoop() {
  return (
    <div className="react-loop">
      <div className="react-loop-steps">
        <span className="react-loop-step">Denken</span>
        <span className="react-loop-sep">→</span>
        <span className="react-loop-step">Suchen</span>
        <span className="react-loop-sep">→</span>
        <span className="react-loop-step">Auswerten</span>
      </div>
      <div className="react-loop-bracket">
        <span className="react-loop-icon">↺</span>
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
          {CHUNKS.map((chunk) => (
            <div key={chunk.id} className={`audio-chunk audio-chunk--${chunk.state}`}>
              {chunk.state === 'active' && <span className="audio-recording-dot" />}
              <WaveformBars />
              <span className="audio-chunk-label">{chunk.label}</span>
            </div>
          ))}
        </div>
        <div className="audio-stream-more">→</div>
      </div>

      <div className="workflow-connector">
        <span className="workflow-connector-arrow">↓</span>
        <span className="workflow-connector-text">je Block</span>
      </div>

      <div className="workflow-pipeline">
        {PIPELINE_STEPS.map((step, i) => (
          <div key={step.label} className="pipeline-step-wrapper">
            <div className={`pipeline-step${step.react ? ' pipeline-step--react' : ''}`}>
              <div className="pipeline-step-label">{step.label}</div>
              {step.react && <ReActLoop />}
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
