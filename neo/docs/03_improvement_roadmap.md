# 🗺️ Improvement Roadmap — AI Navigation Assistant

> **Document scope:** Prioritised roadmap grouping all identified issues into actionable improvement phases. Each item references the issue ID from `02_issues_deep_analysis.md`.

---

## Priority Matrix

| Priority | Criteria | Issues |
|----------|----------|--------|
| **P0 — Fix Now** | Safety-critical bugs, data correctness | CRIT-2, MAJ-5, SIG-6 |
| **P1 — High** | Core feature quality, user experience | CRIT-1, MAJ-3, MAJ-4, SIG-2, SIG-3, SIG-4 |
| **P2 — Medium** | Performance, reliability, architecture | MAJ-1, MAJ-2, CRIT-3, SIG-5 |
| **P3 — Low** | Polish, enhancements, nice-to-have | MIN-1–5, ENH-1–6 |

---

## Phase 1: Safety & Correctness Fixes _(P0)_

These should be fixed **before any demo or presentation**.

### 1.1 Unify Distance Thresholds (CRIT-2)
- [ ] Remove hardcoded thresholds from `server.py` L241–248
- [ ] Remove hardcoded thresholds from `main.py` L263–270
- [ ] Both should read from `decision_engine.urgent_threshold` / `.warning_threshold` / `.info_threshold`
- [ ] Reconcile `config.yaml` values (2.0/4.0/6.0) with the code defaults (0.8/1.5/2.5) — pick one set
- **Effort:** ~30 minutes

### 1.2 Fix Hindi TTS Offline Fallback (MAJ-5)
- [ ] Replace `gTTS` with `pyttsx3` using `espeak-ng` Hindi voice, OR
- [ ] Pre-generate common alert phrases ("bahut paas", "paas", "nazdeek") as cached MP3s for instant offline playback
- [ ] Add a clear system announcement when internet is unavailable: "Hindi voice unavailable offline, switching to English"
- **Effort:** ~2 hours

### 1.3 Fix Alert Queue Broadcasting (SIG-6)
- [ ] Change from single shared `asyncio.Queue` to per-client queues, OR
- [ ] Use a broadcast pattern: pipeline pushes to a list, each send loop gets its own copy
- **Effort:** ~1 hour

---

## Phase 2: Core Feature Improvements _(P1)_

### 2.1 Upgrade Direction System (CRIT-1)
This is the **highest-impact improvement** for navigation quality.

- [ ] Expand from 3 zones to 5 horizontal zones: `FAR_LEFT | LEFT | CENTER | RIGHT | FAR_RIGHT`
  - Boundaries: 0–15%, 15–35%, 35–65%, 65–85%, 85–100%
- [ ] Add 3 vertical zones: `HIGH | MIDDLE | LOW` (using `center_y / frame_height`)
  - Boundaries: 0–30% HIGH, 30–70% MIDDLE, 70–100% LOW
- [ ] Combine into compound directions: "low and slightly left" → "obstacle on the ground to your left"
- [ ] Update voice templates in `decision_engine.py` to use the new zones
- [ ] Update frame annotation in `frame_utils.py` to show 5 zone lines
- **Effort:** ~3–4 hours

### 2.2 Replace Fake ByteTrack with Real Tracking (MAJ-3)
- [ ] **Option A (Recommended):** Use Ultralytics `.track()` API:
  ```python
  results = self.model.track(frame, conf=0.80, persist=True, tracker="bytetrack.yaml")
  ```
  This gives real ByteTrack with Kalman filtering built-in.
- [ ] **Option B:** Implement Hungarian assignment with `scipy.optimize.linear_sum_assignment`
- [ ] Migrate `should_announce` / cooldown logic to work with the new tracker's IDs
- **Effort:** ~4–6 hours

### 2.3 Fix pyttsx3 Re-initialisation (MAJ-4)
- [ ] Create engine once in `_worker()` thread at startup
- [ ] Wrap `engine.runAndWait()` in try/except; only re-init if it fails
- [ ] Add platform check: only apply SAPI5 workaround on Windows
- **Effort:** ~1 hour

### 2.4 Add Path Clearance Announcements (SIG-2)
- [ ] Every N seconds (configurable, e.g., 10s), if no obstacles in CENTER zone within INFO distance:
  - Speak "Path is clear ahead"
- [ ] If obstacles are only on LEFT/RIGHT but CENTER is clear:
  - Speak "Path clear ahead, objects on your left/right"
- **Effort:** ~2 hours

### 2.5 Add Motion/Velocity Estimation (SIG-3)
- [ ] Compute `Δdistance / Δtime` from tracker's distance history per track
- [ ] Classify: APPROACHING (negative velocity) / STATIONARY / RECEDING (positive velocity)
- [ ] For APPROACHING objects, add urgency escalation: if closing fast, bump to next higher alert level
- [ ] Add to voice template: "Person approaching from the left" vs "Parked car on the right"
- **Effort:** ~3–4 hours

### 2.6 Increase Default Resolution (SIG-4)
- [ ] Change `config.yaml` from 320×240 to 640×480
- [ ] Profile latency impact — if too slow, add frame skip (process every 2nd frame)
- [ ] Alternatively: capture at 640×480 but downscale to 320×240 only for MiDaS (which is the bottleneck)
- **Effort:** ~1 hour + testing

---

## Phase 3: Architecture & Reliability _(P2)_

### 3.1 Add Rate Limiting for Groq API (MAJ-1)
- [ ] Add `_min_trigger_interval` (e.g., 10s) for manual 'D' key presses
- [ ] Add HTTP 429 retry with exponential backoff (max 3 retries)
- [ ] Log rate-limit events
- **Effort:** ~1–2 hours

### 3.2 Improve Depth Calibration (MAJ-2)
- [ ] Replace per-frame min/max normalisation with a fixed percentile-based range (e.g., 5th–95th percentile over a rolling window)
- [ ] Add optional interactive calibration: "Hold an object at arm's length and press C"
- [ ] Document the calibration procedure
- **Effort:** ~3–4 hours

### 3.3 Rename Claude → LLM (CRIT-3)
- [ ] Rename `modules/claude_client.py` → `modules/llm_client.py`
- [ ] Rename class `ClaudeClient` → `LLMClient`
- [ ] Update all imports in `main.py`, `server.py`
- [ ] Update README, SETUP, config references
- [ ] Update variable names: `claude_client` → `llm_client`
- **Effort:** ~30 minutes (find-and-replace)

### 3.4 Fix Thread Safety in Server (SIG-5)
- [ ] Use `threading.Lock` for `latest_frame_b64` and `latest_telemetry` writes/reads
- [ ] Or use `asyncio`-safe shared state via `asyncio.Queue` for frame data too
- **Effort:** ~1–2 hours

---

## Phase 4: Polish & Enhancements _(P3)_

### 4.1 Local LLM Integration (ENH-1)
- [ ] Add LM Studio / Ollama backend option in `llm_client.py`
- [ ] Use OpenAI-compatible API (`http://localhost:1234/v1/chat/completions`)
- [ ] Add config option: `llm.backend: "groq" | "local" | "disabled"`
- [ ] The Qwen3-VL-4B model can process images directly — ideal for scene description
- **Effort:** ~3–4 hours

### 4.2 Obstacle Avoidance Suggestions (ENH-2)
- [ ] After computing all detections + directions, identify the largest unobstructed zone
- [ ] Add to voice: "Move left to avoid" / "Step right"
- **Effort:** ~3 hours

### 4.3 Minor Code Fixes (MIN-1 through MIN-5)
- [ ] Cap track IDs with modular arithmetic (MIN-1)
- [ ] Move numpy import to top-level in tracker.py (MIN-4)
- [ ] Add periodic temp file cleanup timer (MIN-3)
- [ ] Add manual "Reconnect" button to dashboard (MIN-5)
- **Effort:** ~1 hour total

### 4.4 Structured Logging / Recording (ENH-5)
- [ ] Add JSON-lines logger that records per-frame: timestamp, detections, alerts, latencies
- [ ] Useful for calibration tuning and demo videos
- **Effort:** ~2 hours

---

## Summary Table

| Phase | Items | Est. Total Effort | Impact |
|-------|-------|-------------------|--------|
| Phase 1 | 3 items | ~3.5 hours | Safety-critical fixes |
| Phase 2 | 6 items | ~14–18 hours | Massive quality leap |
| Phase 3 | 4 items | ~6–8 hours | Reliability & cleanliness |
| Phase 4 | 4 items | ~9–10 hours | Differentiation & polish |
| **Total** | **17 items** | **~33–40 hours** | — |

---

## Quick Wins (< 1 hour each, high visibility)

1. ✅ Unify thresholds (CRIT-2) — 30 min
2. ✅ Rename Claude → LLM (CRIT-3) — 30 min
3. ✅ Fix pyttsx3 re-init (MAJ-4) — 1 hour
4. ✅ Move numpy import (MIN-4) — 5 min
5. ✅ Add path-clear announcement (SIG-2) — 1 hour
