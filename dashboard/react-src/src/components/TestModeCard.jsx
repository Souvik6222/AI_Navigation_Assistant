// components/TestModeCard.jsx
import { useState, useRef } from 'react'

export default function TestModeCard({ telemetry, sendControl }) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef(null)

  const testMode = telemetry?.test_mode || {}
  const isActive = testMode.active || false
  const isPaused = testMode.paused || false
  const progress = testMode.progress || 0
  const filename = testMode.filename || ''
  const currentFrame = testMode.current_frame || 0
  const totalFrames = testMode.total_frames || 0

  async function uploadFile(file) {
    if (!file) return
    setError(null)
    setUploading(true)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/upload-video', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error || 'Upload failed')
      }
    } catch (e) {
      setError('Network error: ' + e.message)
    } finally {
      setUploading(false)
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) uploadFile(file)
    // Reset so same file can be re-selected
    e.target.value = ''
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) uploadFile(file)
  }

  function handleDragOver(e) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave() {
    setDragOver(false)
  }

  function handleStop() {
    sendControl('test_mode_stop', true)
  }

  function handleTogglePause() {
    sendControl('test_mode_pause', !isPaused)
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/></svg>
          Testing Mode
        </span>
        {isActive && (
          <span className="test-active-badge">PROCESSING</span>
        )}
      </div>
      <div className="card-body">
        {/* Upload area */}
        {!isActive && !uploading && (
          <div
            className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => inputRef.current?.click()}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" x2="12" y1="3" y2="15"/>
            </svg>
            <span className="upload-text">Drop a video file here or click to browse</span>
            <span className="upload-hint">.mp4 .avi .mov .mkv .webm</span>
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
          </div>
        )}

        {/* Uploading state */}
        {uploading && (
          <div className="upload-status">
            <div className="upload-spinner" />
            <span>Uploading video...</span>
          </div>
        )}

        {/* Active test mode */}
        {isActive && (
          <div className="test-progress-area">
            <div className="test-filename">{filename}</div>
            <div className="test-progress-bar-track">
              <div
                className="test-progress-bar-fill"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
            <div className="test-progress-info">
              <span>{Math.round(progress * 100)}%</span>
              <span>{currentFrame} / {totalFrames} frames</span>
            </div>
            <div className="test-controls-row" style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
              <button
                className={`btn ${isPaused ? 'btn-accent' : ''}`}
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={handleTogglePause}
              >
                {isPaused ? (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>
                    Resume
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/></svg>
                    Pause
                  </>
                )}
              </button>
              <button
                className="btn btn-danger"
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={handleStop}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
                Stop
              </button>
            </div>
          </div>
        )}

        {/* Completed (progress = 1 and not active) */}
        {!isActive && progress >= 1.0 && filename && !uploading && (
          <div className="test-complete">
            <span className="test-complete-label">Test completed</span>
            <span className="test-complete-file">{filename}</span>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="test-error">{error}</div>
        )}
      </div>
    </div>
  )
}
