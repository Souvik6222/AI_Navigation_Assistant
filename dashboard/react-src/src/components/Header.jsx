// components/Header.jsx
export default function Header({ connected }) {
  return (
    <header className="header">
      <div className="header-brand">
        <div className="brand-icon-svg" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </div>
        <div>
          <div className="brand-name">AI Navigation Assistant</div>
          <div className="brand-sub">YOLOv8 / MiDaS / ByteTrack / FastAPI</div>
        </div>
      </div>
      <div className="header-right">
        <div className={`conn-badge ${connected ? 'connected' : 'disconnected'}`}>
          <span className="conn-dot" />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
      </div>
    </header>
  )
}
