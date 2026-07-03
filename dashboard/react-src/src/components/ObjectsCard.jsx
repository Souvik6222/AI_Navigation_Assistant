// components/ObjectsCard.jsx
const DIR_LABEL = { LEFT: 'L', CENTER: 'C', RIGHT: 'R' }

export default function ObjectsCard({ telemetry }) {
  const objects = telemetry?.objects || []

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
          Tracked Objects
        </span>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          {objects.length} active
        </span>
      </div>
      <div className="card-body" style={{ padding: '8px 10px' }}>
        {objects.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', textAlign: 'center' }}>
            No objects detected
          </p>
        ) : (
          <div className="obj-list">
            {objects.map((obj, i) => (
              <div className="obj-row" key={obj.track_id ?? i}>
                <span className={`obj-dot ${obj.alert_level || 'silent'}`} />
                <span className="obj-label">{obj.label}</span>
                <span className="obj-dist">{obj.distance_m?.toFixed(1)}m</span>
                <span className="obj-dir">
                  {DIR_LABEL[obj.direction?.toUpperCase()] ?? '?'}
                </span>
                <span style={{ fontSize: '0.6rem', color: 'var(--text-secondary)', marginLeft: '2px' }}>
                  #{obj.track_id}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
