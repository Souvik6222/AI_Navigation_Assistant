// components/PerformanceCard.jsx
function LatRow({ label, ms, maxMs, cls }) {
  const pct = Math.min(((ms || 0) / maxMs) * 100, 100)
  return (
    <div className="lat-row">
      <span className="lat-label">{label}</span>
      <div className="lat-track">
        <div className={`lat-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="lat-val">{Math.round(ms || 0)} ms</span>
    </div>
  )
}

export default function PerformanceCard({ telemetry }) {
  const fps = Math.round(telemetry?.fps || 0)
  const lat = telemetry?.latency || {}
  const hw = telemetry?.hw || {}

  const fpsClass = fps >= 20 ? 'good' : fps >= 10 ? 'ok' : 'bad'

  return (
    <div className="card performance-card">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          Performance
        </span>
      </div>
      <div className="card-body">
        {/* FPS + Total latency */}
        <div className="stats-row">
          <div className="stat-tile">
            <span className="stat-label">FPS</span>
            <span className={`stat-value ${fpsClass}`}>{fps}</span>
          </div>
          <div className="stat-tile">
            <span className="stat-label">Total</span>
            <span className="stat-value">{Math.round(lat.total || 0)} ms</span>
          </div>
        </div>

        <hr className="divider" />

        {/* Latency breakdown */}
        <LatRow label="YOLO"  ms={lat.yolo}     maxMs={300} cls="yolo" />
        <LatRow label="MiDaS" ms={lat.midas}    maxMs={300} cls="midas" />
        <LatRow label="Track" ms={lat.tracking} maxMs={50}  cls="tracking" />

        <hr className="divider" />

        {/* HW info */}
        <div className="hw-chips">
          <span className={`hw-chip ${hw.cuda ? 'on' : 'off'}`}>
            CUDA {hw.cuda ? 'ON' : 'OFF'}
          </span>
          <span className="hw-chip">{hw.device || 'CPU'}</span>
          {hw.model && (
            <span className="hw-chip" title={hw.model}>
              {hw.model.split('/').pop()}
            </span>
          )}
          {hw.camera_index !== undefined && (
            <span className="hw-chip">cam:{hw.camera_index}</span>
          )}
        </div>
      </div>
    </div>
  )
}
