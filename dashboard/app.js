// ============================================================
// app.js — AI Navigation Assistant Dashboard Client
// ============================================================
// WebSocket client that connects to the Python FastAPI backend,
// renders live video frames, updates telemetry gauges, handles
// control inputs, and displays the alert activity log.
// ============================================================

(() => {
  "use strict";

  // ---- Configuration ----
  const WS_URL = `ws://${window.location.host}/ws`;
  const MAX_LOG_ENTRIES = 200;
  const CONTROL_DEBOUNCE_MS = 80;

  // ---- DOM References ----
  const DOM = {
    // Connection
    connectionBadge: document.getElementById("connection-badge"),
    connectionText: document.getElementById("connection-text"),

    // Video
    videoFrame: document.getElementById("video-frame"),
    videoPlaceholder: document.getElementById("video-placeholder"),
    liveBadge: document.getElementById("live-badge"),
    resolutionBadge: document.getElementById("resolution-badge"),

    // FPS
    fpsValue: document.getElementById("fps-value"),

    // Latency bars
    latYolo: document.getElementById("lat-yolo"),
    latMidas: document.getElementById("lat-midas"),
    latTracking: document.getElementById("lat-tracking"),
    latTotal: document.getElementById("lat-total"),
    latYoloVal: document.getElementById("lat-yolo-val"),
    latMidasVal: document.getElementById("lat-midas-val"),
    latTrackingVal: document.getElementById("lat-tracking-val"),
    latTotalVal: document.getElementById("lat-total-val"),

    // Hardware
    hwCuda: document.getElementById("hw-cuda"),
    hwCamera: document.getElementById("hw-camera"),
    hwModel: document.getElementById("hw-model"),
    hwDevice: document.getElementById("hw-device"),

    // Detection stats
    objCount: document.getElementById("obj-count"),
    classBadges: document.getElementById("class-badges"),

    // Controls
    ctrlVolume: document.getElementById("ctrl-volume"),
    ctrlRate: document.getElementById("ctrl-rate"),
    ctrlLanguage: document.getElementById("ctrl-language"),
    ctrlConfidence: document.getElementById("ctrl-confidence"),
    ctrlUrgent: document.getElementById("ctrl-urgent"),
    ctrlWarning: document.getElementById("ctrl-warning"),
    ctrlModel: document.getElementById("ctrl-model"),
    ctrlGroq: document.getElementById("ctrl-groq"),
    ctrlGroqInterval: document.getElementById("ctrl-groq-interval"),
    ctrlDisplay: document.getElementById("ctrl-display"),
    ctrlMute: document.getElementById("ctrl-mute"),

    // Control value labels
    volumeVal: document.getElementById("volume-val"),
    rateVal: document.getElementById("rate-val"),
    confVal: document.getElementById("conf-val"),
    urgentVal: document.getElementById("urgent-val"),
    warningVal: document.getElementById("warning-val"),
    groqIntVal: document.getElementById("groq-int-val"),

    // Log
    logContainer: document.getElementById("log-container"),
    logEmpty: document.getElementById("log-empty"),
    btnReplay: document.getElementById("btn-replay"),
    btnClearLog: document.getElementById("btn-clear-log"),
  };

  // ---- State ----
  let ws = null;
  let reconnectDelay = 1000;
  let reconnectTimer = null;
  let logEntryCount = 0;
  let lastAlertMessage = null;
  let debounceTimers = {};

  // ============================================================
  // WebSocket Connection Manager
  // ============================================================

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setConnectionStatus(true);
      reconnectDelay = 1000; // Reset backoff
      addLogEntry("system", "Dashboard connected to server");
    };

    ws.onclose = () => {
      setConnectionStatus(false);
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will fire after this
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.warn("Failed to parse WS message:", e);
      }
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      connect();
      reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
    }, reconnectDelay);
  }

  function setConnectionStatus(connected) {
    if (connected) {
      DOM.connectionBadge.className = "connection-badge connected";
      DOM.connectionText.textContent = "Connected";
    } else {
      DOM.connectionBadge.className = "connection-badge disconnected";
      DOM.connectionText.textContent = "Disconnected";
      DOM.videoFrame.style.display = "none";
      DOM.videoPlaceholder.style.display = "flex";
    }
  }

  function sendControl(key, value) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "control", key, value }));
    }
  }

  // ============================================================
  // Message Router
  // ============================================================

  function handleMessage(msg) {
    switch (msg.type) {
      case "frame":
        renderFrame(msg.data);
        break;
      case "telemetry":
        updateTelemetry(msg);
        break;
      case "alert":
        handleAlert(msg);
        break;
      case "config_sync":
        syncControls(msg.data);
        break;
      default:
        break;
    }
  }

  // ============================================================
  // Frame Renderer
  // ============================================================

  function renderFrame(base64Data) {
    DOM.videoFrame.src = "data:image/jpeg;base64," + base64Data;
    DOM.videoFrame.style.display = "block";
    DOM.videoPlaceholder.style.display = "none";
  }

  // ============================================================
  // Telemetry Updater
  // ============================================================

  function updateTelemetry(data) {
    // FPS
    const fps = Math.round(data.fps || 0);
    DOM.fpsValue.textContent = fps;
    DOM.fpsValue.className = "fps-value " + (fps >= 20 ? "good" : fps >= 10 ? "ok" : "bad");

    // Resolution
    if (data.resolution) {
      DOM.resolutionBadge.textContent = `${data.resolution.width}×${data.resolution.height}`;
    }

    // Latency bars (scale: 0-200ms maps to 0-100%)
    const lat = data.latency || {};
    const maxMs = 200;
    updateLatencyBar("lat-yolo", lat.yolo || 0, maxMs);
    updateLatencyBar("lat-midas", lat.midas || 0, maxMs);
    updateLatencyBar("lat-tracking", lat.tracking || 0, maxMs);
    updateLatencyBar("lat-total", lat.total || 0, maxMs);

    // Hardware info
    if (data.hw) {
      const hw = data.hw;
      DOM.hwCuda.textContent = hw.cuda ? "Enabled" : "Disabled";
      DOM.hwCuda.className = "hw-value " + (hw.cuda ? "active" : "inactive");
      DOM.hwCamera.textContent = `idx ${hw.camera_index ?? 0}`;
      DOM.hwModel.textContent = hw.model || "—";
      DOM.hwDevice.textContent = hw.device || "CPU";
    }

    // Detection stats
    const objects = data.objects || [];
    DOM.objCount.textContent = objects.length;

    // Class badges
    const classSet = new Set(objects.map((o) => o.label));
    const currentBadges = DOM.classBadges.querySelectorAll(".class-badge");
    const currentLabels = new Set();
    currentBadges.forEach((b) => currentLabels.add(b.textContent));

    // Only update if classes changed
    if (!setsEqual(classSet, currentLabels)) {
      DOM.classBadges.innerHTML = "";
      classSet.forEach((cls) => {
        const badge = document.createElement("span");
        badge.className = "class-badge";
        badge.textContent = cls;
        DOM.classBadges.appendChild(badge);
      });
    }
  }

  function updateLatencyBar(id, ms, maxMs) {
    const bar = document.getElementById(id);
    const valEl = document.getElementById(id + "-val");
    if (bar) {
      const pct = Math.min((ms / maxMs) * 100, 100);
      bar.style.width = pct + "%";
    }
    if (valEl) {
      valEl.textContent = Math.round(ms) + " ms";
    }
  }

  function setsEqual(a, b) {
    if (a.size !== b.size) return false;
    for (const item of a) {
      if (!b.has(item)) return false;
    }
    return true;
  }

  // ============================================================
  // Alert Handler
  // ============================================================

  function handleAlert(data) {
    const level = (data.level || "info").toLowerCase();
    const message = data.message || "";
    const timestamp = data.timestamp || new Date().toLocaleTimeString("en-GB", { hour12: false });

    lastAlertMessage = { level, message, timestamp };
    addLogEntry(level, message, timestamp);
  }

  function addLogEntry(level, message, timestamp) {
    if (!timestamp) {
      timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
    }

    // Hide empty state
    if (DOM.logEmpty) DOM.logEmpty.style.display = "none";

    // Create entry
    const entry = document.createElement("div");
    entry.className = "log-entry" + (level === "urgent" ? " urgent-pulse" : "");

    entry.innerHTML = `
      <span class="log-timestamp">${escapeHtml(timestamp)}</span>
      <span class="log-badge ${escapeHtml(level)}">${escapeHtml(level.toUpperCase())}</span>
      <span class="log-message">${escapeHtml(message)}</span>
    `;

    DOM.logContainer.appendChild(entry);
    logEntryCount++;

    // Auto-scroll
    DOM.logContainer.scrollTop = DOM.logContainer.scrollHeight;

    // Trim old entries
    while (logEntryCount > MAX_LOG_ENTRIES) {
      const first = DOM.logContainer.querySelector(".log-entry");
      if (first) {
        first.remove();
        logEntryCount--;
      } else {
        break;
      }
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ============================================================
  // Config Sync — Update controls from server state
  // ============================================================

  function syncControls(cfg) {
    if (!cfg) return;

    if (cfg.volume !== undefined) {
      DOM.ctrlVolume.value = cfg.volume;
      DOM.volumeVal.textContent = cfg.volume + "%";
    }
    if (cfg.speech_rate !== undefined) {
      DOM.ctrlRate.value = cfg.speech_rate;
      DOM.rateVal.textContent = cfg.speech_rate + " wpm";
    }
    if (cfg.language !== undefined) {
      DOM.ctrlLanguage.value = cfg.language;
    }
    if (cfg.confidence_threshold !== undefined) {
      DOM.ctrlConfidence.value = cfg.confidence_threshold;
      DOM.confVal.textContent = parseFloat(cfg.confidence_threshold).toFixed(2);
    }
    if (cfg.urgent_threshold !== undefined) {
      DOM.ctrlUrgent.value = cfg.urgent_threshold;
      DOM.urgentVal.textContent = parseFloat(cfg.urgent_threshold).toFixed(1) + " m";
    }
    if (cfg.warning_threshold !== undefined) {
      DOM.ctrlWarning.value = cfg.warning_threshold;
      DOM.warningVal.textContent = parseFloat(cfg.warning_threshold).toFixed(1) + " m";
    }
    if (cfg.model_path !== undefined) {
      DOM.ctrlModel.value = cfg.model_path;
    }
    if (cfg.groq_enabled !== undefined) {
      DOM.ctrlGroq.checked = cfg.groq_enabled;
    }
    if (cfg.groq_interval !== undefined) {
      DOM.ctrlGroqInterval.value = cfg.groq_interval;
      DOM.groqIntVal.textContent = cfg.groq_interval + " s";
    }
    if (cfg.show_display !== undefined) {
      DOM.ctrlDisplay.checked = cfg.show_display;
    }
    if (cfg.mute_all !== undefined) {
      DOM.ctrlMute.checked = cfg.mute_all;
    }
  }

  // ============================================================
  // Control Event Bindings
  // ============================================================

  function debouncedSend(key, value) {
    if (debounceTimers[key]) clearTimeout(debounceTimers[key]);
    debounceTimers[key] = setTimeout(() => {
      sendControl(key, value);
    }, CONTROL_DEBOUNCE_MS);
  }

  // Sliders
  DOM.ctrlVolume.addEventListener("input", () => {
    const v = parseInt(DOM.ctrlVolume.value);
    DOM.volumeVal.textContent = v + "%";
    debouncedSend("volume", v);
  });

  DOM.ctrlRate.addEventListener("input", () => {
    const v = parseInt(DOM.ctrlRate.value);
    DOM.rateVal.textContent = v + " wpm";
    debouncedSend("speech_rate", v);
  });

  DOM.ctrlConfidence.addEventListener("input", () => {
    const v = parseFloat(DOM.ctrlConfidence.value);
    DOM.confVal.textContent = v.toFixed(2);
    debouncedSend("confidence_threshold", v);
  });

  DOM.ctrlUrgent.addEventListener("input", () => {
    const v = parseFloat(DOM.ctrlUrgent.value);
    DOM.urgentVal.textContent = v.toFixed(1) + " m";
    debouncedSend("urgent_threshold", v);
  });

  DOM.ctrlWarning.addEventListener("input", () => {
    const v = parseFloat(DOM.ctrlWarning.value);
    DOM.warningVal.textContent = v.toFixed(1) + " m";
    debouncedSend("warning_threshold", v);
  });

  DOM.ctrlGroqInterval.addEventListener("input", () => {
    const v = parseInt(DOM.ctrlGroqInterval.value);
    DOM.groqIntVal.textContent = v + " s";
    debouncedSend("groq_interval", v);
  });

  // Selects
  DOM.ctrlLanguage.addEventListener("change", () => {
    sendControl("language", DOM.ctrlLanguage.value);
  });

  DOM.ctrlModel.addEventListener("change", () => {
    sendControl("model_path", DOM.ctrlModel.value);
    addLogEntry("system", `Switching YOLO model to ${DOM.ctrlModel.value}...`);
  });

  // Toggles
  DOM.ctrlGroq.addEventListener("change", () => {
    sendControl("groq_enabled", DOM.ctrlGroq.checked);
  });

  DOM.ctrlDisplay.addEventListener("change", () => {
    sendControl("show_display", DOM.ctrlDisplay.checked);
  });

  DOM.ctrlMute.addEventListener("change", () => {
    sendControl("mute_all", DOM.ctrlMute.checked);
  });

  // Buttons
  DOM.btnReplay.addEventListener("click", () => {
    sendControl("replay_last", true);
    if (lastAlertMessage) {
      addLogEntry("system", `Replaying: "${lastAlertMessage.message}"`);
    }
  });

  DOM.btnClearLog.addEventListener("click", () => {
    DOM.logContainer.innerHTML = "";
    logEntryCount = 0;
    DOM.logContainer.innerHTML = '<div class="log-empty" id="log-empty">Log cleared</div>';
  });

  // ============================================================
  // Init
  // ============================================================
  connect();

})();
