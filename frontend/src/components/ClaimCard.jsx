import React from 'react'

// Markdown regex patterns - compiled once at module load for better performance
const MARKDOWN_BOLD_PATTERN = /\*\*(.+?)\*\*/g
const MARKDOWN_ITALIC_PATTERN = /(?<!\*)\*([^*]+?)\*(?!\*)/g
const MARKDOWN_LINK_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g

const getConsistencyColor = (consistency) => {
  const lower = consistency?.toLowerCase() || ''
  if (lower === 'hoch') return '#22c55e'
  if (lower === 'niedrig') return '#ef4444'
  if (lower === 'mittel') return '#f59e0b'
  return '#6b7280' // unklar or unknown
}

const getConsistencyClass = (consistency) => {
  const lower = consistency?.toLowerCase() || ''
  if (lower === 'hoch') return 'verdict-richtig'
  if (lower === 'niedrig') return 'verdict-falsch'
  if (lower === 'mittel') return 'verdict-teilweise'
  return 'verdict-unbelegt' // unklar or unknown
}

// Simple Markdown formatting (bold, italic, links)
const formatMarkdown = (text) => {
  if (!text) return text

  let match
  const matches = []

  // Reset lastIndex for global regex patterns (they maintain state)
  MARKDOWN_BOLD_PATTERN.lastIndex = 0
  MARKDOWN_ITALIC_PATTERN.lastIndex = 0
  MARKDOWN_LINK_PATTERN.lastIndex = 0

  // Pattern for **bold**
  while ((match = MARKDOWN_BOLD_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'bold',
      start: match.index,
      end: match.index + match[0].length,
      content: match[1]
    })
  }

  // Pattern for *italic*
  while ((match = MARKDOWN_ITALIC_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'italic',
      start: match.index,
      end: match.index + match[0].length,
      content: match[1]
    })
  }

  // Pattern for [text](url)
  while ((match = MARKDOWN_LINK_PATTERN.exec(text)) !== null) {
    matches.push({
      type: 'link',
      start: match.index,
      end: match.index + match[0].length,
      text: match[1],
      url: match[2]
    })
  }

  // Sort matches by position
  matches.sort((a, b) => a.start - b.start)

  // Build React elements
  if (matches.length === 0) {
    return text
  }

  const elements = []
  let currentIndex = 0

  matches.forEach((match, idx) => {
    // Text before the match
    if (match.start > currentIndex) {
      elements.push(text.substring(currentIndex, match.start))
    }

    // The match itself
    if (match.type === 'bold') {
      elements.push(<strong key={`bold-${idx}`}>{match.content}</strong>)
    } else if (match.type === 'italic') {
      elements.push(<em key={`italic-${idx}`}>{match.content}</em>)
    } else if (match.type === 'link') {
      elements.push(
        <a key={`link-${idx}`} href={match.url} target="_blank" rel="noopener noreferrer" className="begruendung-link">
          {match.text}
        </a>
      )
    }

    currentIndex = match.end
  })

  // Rest of the text
  if (currentIndex < text.length) {
    elements.push(text.substring(currentIndex))
  }

  return elements.length > 0 ? <>{elements}</> : text
}

// Format reasoning: line breaks and simple Markdown
const formatBegruendung = (text) => {
  if (!text) return null

  // Replace \n\n with paragraphs
  const paragraphs = text.split(/\n\n+/).filter(p => p.trim())

  return paragraphs.map((para, idx) => {
    // Replace single \n with <br>
    const lines = para.split('\n')
    return (
      <p key={idx} className="begruendung-text">
        {lines.map((line, lineIdx) => (
          <React.Fragment key={lineIdx}>
            {lineIdx > 0 && <br />}
            {formatMarkdown(line)}
          </React.Fragment>
        ))}
      </p>
    )
  })
}

export function ClaimCard({ claim, isExpanded, onToggle }) {
  const consistencyClass = getConsistencyClass(claim.consistency)

  return (
    <div className={`claim-card ${consistencyClass}`}>
      <div className="claim-header">
        <div className="claim-text">{claim.behauptung}</div>
        <button
          className="expand-button"
          onClick={onToggle}
          aria-label={isExpanded ? 'Einklappen' : 'Ausklappen'}
        >
          {isExpanded ? '▼' : '▶'}
        </button>
      </div>

      {isExpanded && (
        <div className="claim-details">
          <div className="detail-section">
            <h3>Datenbasierte Fundierung</h3>
            <div
              className="verdict-badge"
              style={{ backgroundColor: getConsistencyColor(claim.consistency) }}
            >
              {claim.consistency}
            </div>
          </div>

          <div className="detail-section">
            <h3>Begrundung</h3>
            {claim.begruendung ? (
              <div className="begruendung-container">
                {formatBegruendung(claim.begruendung)}
              </div>
            ) : (
              <p className="begruendung-text no-begruendung">
                Keine Begrundung verfugbar
              </p>
            )}
          </div>

          {claim.quellen && claim.quellen.length > 0 && (
            <div className="detail-section">
              <h3>Quellen</h3>
              <ul className="sources-list">
                {claim.quellen.map((quelle, idx) => {
                  const url = typeof quelle === 'object' ? quelle.url : quelle;
                  const title = typeof quelle === 'object' && quelle.title ? quelle.title : url;
                  return (
                    <li key={idx}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="source-link"
                      >
                        {title}
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
