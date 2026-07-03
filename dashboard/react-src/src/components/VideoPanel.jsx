// components/VideoPanel.jsx
export default function VideoPanel({ frame, telemetry }) {
  const res = telemetry?.resolution
  const hasFrame = Boolean(frame)

  return (
    <section className="card video-panel" aria-label="Live camera feed">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
          Live Camera Feed
        </span>
      </div>
      <div className="video-wrap">
        {hasFrame && (
          <>
            <img
              src={`data:image/jpeg;base64,${frame}`}
              alt="Live annotated camera feed"
            />
            <div className="video-overlays">
              <span className="badge badge-live">LIVE</span>
              {res && (
                <span className="badge badge-res">
                  {res.width} x {res.height}
                </span>
              )}
            </div>
          </>
        )}
        {!hasFrame && (
          <div className="video-placeholder">
            <svg className="placeholder-svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" opacity="0.3">
              <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/>
              <path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/>
              <circle cx="12" cy="12" r="2"/>
              <path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/>
              <path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/>
            </svg>
            <span>Waiting for camera feed...</span>
            <span style={{ fontSize: '0.7rem', opacity: 0.5 }}>
              Run <code style={{ color: 'var(--accent)' }}>python server.py</code>
            </span>
          </div>
        )}
      </div>
    </section>
  )
}
