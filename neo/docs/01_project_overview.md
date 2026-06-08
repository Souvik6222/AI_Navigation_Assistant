# 📖 Project Overview — AI Navigation Assistant

> **Document scope:** Complete technical walkthrough of every module, how data flows end-to-end, and what each file does.

---

## 1. What Is This Project?

The **AI Navigation Assistant** is a real-time computer-vision application that helps **visually impaired people navigate safely** using only a laptop webcam. It:

1. Captures live video frames.
2. Detects obstacles (people, chairs, cars, stairs, etc.) with **YOLOv8**.
3. Estimates how far away each obstacle is with **MiDaS monocular depth estimation**.
4. Determines whether each obstacle is on the user's **LEFT, CENTER, or RIGHT**.
5. Tracks objects across frames to avoid spamming the same alert repeatedly.
6. Runs a rule-based **Decision Engine** that prioritises alerts by danger level.
7. Speaks the alerts aloud in **English (offline)** or **Hindi (via gTTS / internet)**.
8. Optionally calls the **Groq API** (LLaMA 4 Scout 17B) for natural-language scene descriptions.

Two execution modes:
- **Desktop mode** (`main.py`) — OpenCV window + voice alerts.
- **Web Dashboard mode** (`server.py`) — FastAPI + WebSocket streaming to a browser UI.

---

## 2. Architecture Diagram

```
 ┌─────────────────────────────────────────────────────────────┐
 │                      FRAME CAPTURE                         │
 │  cv2.VideoCapture → resize to 320×240 (config default)     │
 └─────────────────┬───────────────────────────────────────────┘
                   │ raw frame (BGR, numpy)
         ┌─────────┴──────────┐
         ▼                    ▼
 ┌───────────────┐   ┌─────────────────┐
 │  detector.py  │   │depth_estimator.py│
 │  YOLOv8x      │   │  MiDaS Small    │
 │  → bboxes     │   │  → depth map    │
 └───────┬───────┘   └────────┬────────┘
         │ List[det]          │ np.ndarray (H×W, 0-1)
         └─────────┬──────────┘
                   ▼
         ┌─────────────────┐
         │ direction.py    │  Enriches each det with
         │ + calibration   │  det["direction"] + det["distance_m"]
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │  tracker.py     │  IoU-based matching → persistent track IDs
         │  (ByteTrack-    │  + cooldown / stability logic
         │   inspired)     │  → should_announce flag
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │decision_engine.py│  Rule-based: distance → URGENT/WARNING/INFO/SILENT
         │                  │  Priority scoring + max 2 alerts/frame
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │   voice.py      │  Async TTS in background thread
         │ pyttsx3 (EN)    │  Queue-based, never blocks pipeline
         │ gTTS (HI)       │
         └─────────────────┘
                  ↕  (async, optional, every 30s or 'D' key)
         ┌─────────────────┐
         │claude_client.py │  Groq API → LLaMA 4 Scout 17B
         │ Scene description│  Vision + text prompt → spoken via voice.py
         └─────────────────┘
```

---

## 3. File-by-File Breakdown

### Entry Points

| File | Purpose |
|------|---------|
| `main.py` | Desktop-mode entry point. Opens webcam, runs pipeline loop, renders OpenCV window. |
| `server.py` | Web-dashboard entry point. Same pipeline in a background thread; FastAPI + WebSocket streams frames/telemetry/alerts to browser. |
| `config.yaml` | All tunable parameters: camera, detection, depth, tracking, decision, voice, Groq, display, logging. |
| `requirements.txt` | 37 lines of pip dependencies. |
| `.env.example` | Template for `GROQ_API_KEY`. |

### `modules/` — Core Pipeline

| File | Class | Responsibility |
|------|-------|----------------|
| `detector.py` | `ObjectDetector` | Wraps Ultralytics YOLO. Runs inference, filters by confidence (≥80%), bbox area (≥1% frame), and a whitelist of 28 COCO classes. Supports hot-swap via `swap_model()`. |
| `depth_estimator.py` | `DepthEstimator` | Loads MiDaS Small via `torch.hub`. Runs depth inference, normalises to 0–1, applies temporal smoothing (running mean over 3 frames). Delegates distance conversion to `DepthCalibrator`. |
| `direction.py` | `get_direction()` | Pure function. Divides frame into 3 equal vertical strips (0-33% LEFT, 33-66% CENTER, 66-100% RIGHT). |
| `tracker.py` | `ObjectTracker` | Lightweight IoU-based tracker (not actual ByteTrack). Assigns persistent IDs, manages cooldowns (7s default), distance-change re-announce (50%), multi-frame stability (5 frames). |
| `decision_engine.py` | `DecisionEngine` | Rule-based. Maps distance to URGENT/WARNING/INFO/SILENT. Priority scoring with bonuses for CENTER (+2.0), dynamic obstacles (+0.5). Max 2 alerts per frame. Hardcoded bilingual messages. |
| `voice.py` | `VoiceEngine` | Daemon thread with `queue.Queue`. English: `pyttsx3` (offline, re-init per utterance). Hindi: `gTTS` → temp MP3 → `pygame.mixer`. |
| `claude_client.py` | `ClaudeClient` | Actually uses **Groq** API (not Anthropic Claude). Sends annotated frame + detection JSON → receives natural-language scene description. Auto-triggers every 30s or manually with 'D'. |

### `utils/` — Support

| File | Class/Function | Responsibility |
|------|----------------|----------------|
| `calibration.py` | `DepthCalibrator` | Converts normalised MiDaS depth → metres via `distance = scale / (depth + offset)`. Samples central 20% of bbox, uses median. Clamps to [0.3m, 6.0m]. |
| `frame_utils.py` | `annotate_frame()`, `draw_status_bar()`, `frame_to_base64()` | Draws colour-coded bboxes, zone lines, status bar. Encodes frames for API/WebSocket. |
| `logger.py` | `get_logger()` | Coloured console logging with ANSI codes. Optional file handler. |

### `dashboard/` — Web Frontend

| File | Purpose |
|------|---------|
| `index.html` | Single-page dashboard. Grid layout: video panel, sidebar (performance, system info, controls), bottom alert log. |
| `style.css` | 1000+ lines. Dark glassmorphism theme with Inter/JetBrains Mono fonts, neon teal accents, animated gradients. |
| `app.js` | WebSocket client. Renders base64 JPEG frames, updates telemetry bars, routes alert/control messages, debounces slider inputs. |

---

## 4. Data Flow Per Frame (Detailed)

```
1. cap.read()                              → raw BGR frame
2. resize_frame(frame, 320, 240)           → standardised dimensions
3. detector.detect(frame)                  → List of dicts:
       { label, confidence, bbox(x1,y1,x2,y2), center_x, center_y, area, class_id }
4. depth_estimator.estimate(frame)         → depth_map: np.ndarray (H×W, float32, 0-1)
5. For each detection:
     direction.get_direction(center_x, W)  → "LEFT" | "CENTER" | "RIGHT"
     depth_estimator.get_distance(map,bbox)→ float (metres)
6. tracker.update(detections, W)           → tracked_objects:
       extends each det with { track_id, tracked_frames, should_announce }
7. decision_engine.evaluate(tracked_objects)→ List[Alert] (max 2):
       Alert { level, message_en, message_hi, tracked_object, priority_score }
8. For each alert:
     voice_engine.speak(message, lang)     → enqueued for async TTS
9. annotate_frame(frame, tracked_objects)  → annotated BGR frame
10. (server mode) encode frame → base64 → WebSocket broadcast
11. (optional) claude_client auto-trigger  → async Groq API call → voice
```

---

## 5. Anti-Hallucination Safeguards (6 Layers)

| # | Layer | Where | Threshold |
|---|-------|-------|-----------|
| 1 | **Confidence thresholding** | `detector.py` line 65 | ≥ 80% |
| 2 | **Bbox area filter** | `detector.py` line 66 | ≥ 1% of frame |
| 3 | **Class whitelist** | `detector.py` line 67 | 28 navigation-relevant COCO classes |
| 4 | **Multi-frame verification** | `decision_engine.py` line 153 | ≥ 3 consecutive frames |
| 5 | **Tracking stability** | `tracker.py` line 179 | ≥ 5 tracked frames before first announce |
| 6 | **Distance variance check** | `decision_engine.py` line 158–163 | ≤ 20% coefficient of variation |

**Design principle:** The LLM (Groq) is **never** in the safety-critical path. All stop/go decisions are purely rule-based.

---

## 6. Configuration Reference (`config.yaml`)

| Section | Key Parameters |
|---------|---------------|
| `camera` | `device_index: 0`, `frame_width: 320`, `frame_height: 240`, `fps: 30` |
| `detection` | `model_path: yolov8x.pt`, `confidence_threshold: 0.80`, `min_bbox_area_ratio: 0.01`, 28 `target_classes` |
| `depth` | `model_type: MiDaS_small`, `temporal_smoothing_frames: 3`, calibration: `scale: 2.0, offset: 0.2` |
| `tracking` | `alert_cooldown_seconds: 7.0`, `re_announce_distance_change_threshold: 0.50`, `min_tracked_frames: 5` |
| `decision` | `urgent: 2.0m`, `warning: 4.0m`, `info: 6.0m`, `max_simultaneous_alerts: 2` |
| `voice` | `default_language: en`, `pyttsx3_rate: 175`, `queue_max_size: 10` |
| `groq` | `model: llama-4-scout-17b-16e-instruct`, `auto_trigger_interval: 30s`, `max_tokens: 300` |

> **Note:** `config.yaml` says `urgent: 2.0m` and `warning: 4.0m`, but `decision_engine.py` defaults to `0.8m` and `1.5m`. The server's annotation code also hardcodes `0.8m`/`1.5m`/`2.5m`. These are **inconsistent** — see the issues document.
