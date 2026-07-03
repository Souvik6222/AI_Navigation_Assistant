// components/ControlsCard.jsx
import { useRef } from 'react'

function SliderRow({ label, id, min, max, step = 1, value, onChange, display }) {
  return (
    <div className="ctrl-row">
      <span className="ctrl-label">{label}</span>
      <input
        type="range"
        id={id}
        min={min}
        max={max}
        step={step}
        value={value ?? min}
        onChange={e => onChange(Number(e.target.value))}
        aria-label={label}
      />
      <span className="ctrl-val">{display}</span>
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <div className="toggle-wrap">
      <span className="ctrl-label">{label}</span>
      <label className="toggle">
        <input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} />
        <span className="toggle-track" />
        <span className="toggle-thumb" />
      </label>
    </div>
  )
}

export default function ControlsCard({ config = {}, onControl, sendControl }) {
  const debounceRef = useRef({})

  function debounced(key, value) {
    clearTimeout(debounceRef.current[key])
    debounceRef.current[key] = setTimeout(() => onControl(key, value), 80)
  }

  const vol = config.volume ?? 100
  const rate = config.speech_rate ?? 175
  const conf = config.confidence_threshold ?? 0.80
  const groqInt = config.groq_interval ?? 30
  const muted = config.mute_all ?? false
  const groqEnabled = config.groq_enabled ?? true
  const showDisplay = config.show_display ?? true
  const lang = config.language ?? 'en'

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
          Controls
        </span>
      </div>
      <div className="card-body">
        <div className="ctrl-group">
          {/* Sound */}
          <SliderRow
            label="Volume" id="ctrl-volume"
            min={0} max={100} value={vol}
            display={`${vol}%`}
            onChange={v => debounced('volume', v)}
          />
          <SliderRow
            label="Speech rate" id="ctrl-rate"
            min={100} max={300} step={5} value={rate}
            display={`${rate} wpm`}
            onChange={v => debounced('speech_rate', v)}
          />

          {/* Language */}
          <div className="ctrl-row">
            <span className="ctrl-label">Language</span>
            <select
              value={lang}
              onChange={e => onControl('language', e.target.value)}
              style={{ flex: 1, marginLeft: '8px' }}
            >
              <option value="en">English</option>
              <option value="hi">Hindi</option>
            </select>
          </div>

          <hr className="divider" />

          {/* Detection */}
          <SliderRow
            label="Confidence" id="ctrl-conf"
            min={0.10} max={1.0} step={0.05} value={conf}
            display={conf.toFixed ? conf.toFixed(2) : conf}
            onChange={v => debounced('confidence_threshold', v)}
          />

          {/* YOLO model */}
          <div className="ctrl-row">
            <span className="ctrl-label">YOLO model</span>
            <select
              value={config.model_path ?? 'yolov8x.onnx'}
              onChange={e => onControl('model_path', e.target.value)}
              style={{ flex: 1, marginLeft: '8px' }}
            >
              <option value="yolov8x.onnx">YOLOv8x ONNX</option>
              <option value="yolov8x.pt">YOLOv8x PT</option>
              <option value="yolov8n.pt">YOLOv8n (Fast)</option>
            </select>
          </div>

          <hr className="divider" />

          {/* Toggles */}
          <Toggle label="Mute all audio" checked={muted}
            onChange={v => onControl('mute_all', v)} />
          <Toggle label="Groq Vision" checked={groqEnabled}
            onChange={v => onControl('groq_enabled', v)} />

          {groqEnabled && (
            <SliderRow
              label="Groq interval" id="ctrl-groq-int"
              min={5} max={120} step={5} value={groqInt}
              display={`${groqInt}s`}
              onChange={v => debounced('groq_interval', v)}
            />
          )}

          <Toggle label="Local cv2 window" checked={showDisplay}
            onChange={v => onControl('show_display', v)} />
        </div>
      </div>
    </div>
  )
}
