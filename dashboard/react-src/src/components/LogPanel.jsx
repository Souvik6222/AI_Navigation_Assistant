// components/LogPanel.jsx
import { useEffect, useRef } from 'react'

export default function LogPanel({ alerts, onClear, sendControl }) {
  const bottomRef = useRef(null)

  // Auto-scroll to bottom when new alerts arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [alerts])

  function handleReplay() {
    sendControl('replay_last', true)
  }

  return (
    <section className="card log-panel" aria-label="Activity log">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/><line x1="10" x2="8" y1="9" y2="9"/></svg>
          Activity Log
        </span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button className="btn btn-accent" id="btn-replay" onClick={handleReplay}>
            Replay
          </button>
          <button className="btn btn-danger" id="btn-clear-log" onClick={onClear}>
            Clear
          </button>
        </div>
      </div>
      <div className="log-body">
        {alerts.length === 0 ? (
          <div className="log-empty">
            No alerts yet -- start the navigation assistant to see activity
          </div>
        ) : (
          alerts.map(entry => (
            <div
              key={entry.id}
              className={`log-entry ${entry.level}`}
            >
              <span className="log-time">{entry.timestamp}</span>
              <span className={`log-level ${entry.level}`}>
                {entry.level.toUpperCase()}
              </span>
              <span className="log-msg">{entry.message}</span>
              {entry.object && (
                <span style={{
                  fontSize: '0.65rem',
                  color: 'var(--text-secondary)',
                  fontFamily: 'JetBrains Mono, monospace',
                  marginLeft: 'auto',
                  flexShrink: 0,
                }}>
                  #{entry.object.track_id} | {entry.object.distance_m}m | {entry.object.direction}
                </span>
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
