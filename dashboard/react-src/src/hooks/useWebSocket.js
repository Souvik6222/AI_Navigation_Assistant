// hooks/useWebSocket.js — WebSocket connection manager
import { useState, useEffect, useRef, useCallback } from 'react'

const WS_URL = `ws://${window.location.host}/ws`

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [frame, setFrame] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [config, setConfig] = useState(null)

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectDelay = useRef(1000)

  const sendControl = useCallback((key, value) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'control', key, value }))
    }
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      addSystemLog('Dashboard connected to server')
    }

    ws.onclose = () => {
      setConnected(false)
      scheduleReconnect()
    }

    ws.onerror = () => { /* onclose fires after */ }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        switch (msg.type) {
          case 'frame':
            setFrame(msg.data)
            break
          case 'telemetry':
            setTelemetry(msg)
            break
          case 'alert':
            handleAlert(msg)
            break
          case 'config_sync':
            setConfig(msg.data)
            break
        }
      } catch {}
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    reconnectTimer.current = setTimeout(() => {
      connect()
      reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 30000)
    }, reconnectDelay.current)
  }, [connect])

  function addSystemLog(message) {
    const entry = {
      id: Date.now() + Math.random(),
      level: 'system',
      message,
      timestamp: new Date().toLocaleTimeString('en-GB', { hour12: false }),
    }
    setAlerts(prev => [...prev.slice(-199), entry])
  }

  function handleAlert(data) {
    const entry = {
      id: Date.now() + Math.random(),
      level: (data.level || 'info').toLowerCase(),
      message: data.message || '',
      timestamp: data.timestamp || new Date().toLocaleTimeString('en-GB', { hour12: false }),
      object: data.object,
    }
    setAlerts(prev => [...prev.slice(-199), entry])
  }

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clearAlerts = useCallback(() => setAlerts([]), [])

  return { connected, frame, telemetry, alerts, config, sendControl, clearAlerts }
}
