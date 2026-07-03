// App.jsx — 3-Column Root layout (Swapped columns: Video Center, Log Left)
import Header from './components/Header'
import VideoPanel from './components/VideoPanel'
import PerformanceCard from './components/PerformanceCard'
import LogPanel from './components/LogPanel'
import TestModeCard from './components/TestModeCard'
import ObjectsCard from './components/ObjectsCard'
import ControlsCard from './components/ControlsCard'
import { useWebSocket } from './hooks/useWebSocket'
import { useState } from 'react'

export default function App() {
  const { connected, frame, telemetry, alerts, config, sendControl, clearAlerts } = useWebSocket()
  const [localCfg, setLocalCfg] = useState({})

  // Merge config: prioritize local changes (localCfg) over server defaults (config)
  const cfg = config ? { ...config, ...localCfg } : localCfg

  function ctrl(key, value) {
    setLocalCfg(prev => ({ ...prev, [key]: value }))
    sendControl(key, value)
  }

  return (
    <div className="dashboard">
      <Header connected={connected} />
      
      {/* Left Column: Activity Log & Performance telemetry */}
      <div className="dash-col-left">
        <LogPanel alerts={alerts} onClear={clearAlerts} sendControl={sendControl} />
        <PerformanceCard telemetry={telemetry} />
      </div>

      {/* Center Column: Massive high-priority Live Video Feed */}
      <div className="dash-col-center">
        <VideoPanel frame={frame} telemetry={telemetry} />
      </div>

      {/* Right Column: Testing mode uploads, Tracked Objects list, and system controls */}
      <div className="dash-col-right">
        <TestModeCard telemetry={telemetry} sendControl={sendControl} />
        <ObjectsCard telemetry={telemetry} />
        <ControlsCard config={cfg} onControl={ctrl} sendControl={sendControl} />
      </div>
    </div>
  )
}
