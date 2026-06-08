# 🔍 Deep Issue Analysis — AI Navigation Assistant

> **Document scope:** Every issue found through line-by-line code audit, grouped by severity and category. Each issue includes the exact file/line, what's wrong, why it matters, and a proposed fix direction.

---

## Table of Contents

- [🔴 Critical Issues (Safety / Correctness)](#-critical-issues)
- [🟠 Major Issues (Latency / Performance)](#-major-issues)
- [🟡 Significant Issues (Architecture / Design)](#-significant-issues)
- [🔵 Minor Issues (Code Quality / Bugs)](#-minor-issues)
- [⚪ Enhancement Opportunities](#-enhancement-opportunities)

---

## 🔴 Critical Issues

### CRIT-1: Direction System Is Far Too Primitive (3 Zones Only)

**File:** `modules/direction.py` — lines 6–34  
**Severity:** Critical for navigation safety

**The Problem:**  
The entire directional awareness system is a single function that splits the frame into exactly 3 equal strips (LEFT / CENTER / RIGHT). This is dangerously oversimplified:

- **No vertical axis at all.** The system cannot distinguish between an obstacle at foot level (a curb) vs. overhead (a sign). A visually impaired user could walk into a low bollard that the system reports as "CENTER" with no indication it's at ground level.
- **No granularity.** "LEFT" covers the full 0–33% range. An object at 5% (far periphery, barely in frame) and one at 30% (almost center) both produce the same voice alert. The user gets identical guidance for radically different situations.
- **No angular estimation.** The system doesn't consider camera field-of-view (FoV). "33% from left edge" on a 60° FoV camera means something very different than on a 120° FoV camera.
- **No "SLIGHTLY LEFT" or "STRAIGHT AHEAD" distinction.** The CENTER zone is huge (33% of the frame). An object at 34% (just barely center-left) and one at exactly 50% (dead center) both say "ahead".

**Why it matters:**  
For a visually impaired user, "ahead" vs. "slightly to your left" is the difference between walking into something and safely avoiding it.

**Proposed fix direction:**  
- Expand to 5+ zones: FAR_LEFT, LEFT, CENTER, RIGHT, FAR_RIGHT  
- Add vertical zones: HIGH, MIDDLE, LOW (using `center_y`)  
- Consider clock-position language: "at your 10 o'clock", "at your 2 o'clock"  
- Consider angular estimation based on configurable camera FoV  

---

### CRIT-2: Threshold Inconsistency Between Config, Decision Engine, and Server

**Files:**  
- `config.yaml` lines 74–78: `urgent: 2.0`, `warning: 4.0`, `info: 6.0`  
- `modules/decision_engine.py` lines 114–116: defaults to `0.8`, `1.5`, `2.5`  
- `server.py` lines 241–248: hardcodes `0.8`, `1.5`, `2.5` for annotation colors  

**The Problem:**  
Three different places define distance thresholds, and they **contradict each other**:

| Source | Urgent | Warning | Info |
|--------|--------|---------|------|
| `config.yaml` | 2.0m | 4.0m | 6.0m |
| `decision_engine.py` defaults | 0.8m | 1.5m | 2.5m |
| `server.py` hardcoded | 0.8m | 1.5m | 2.5m |

When `config.yaml` is loaded, the Decision Engine will use `2.0m / 4.0m / 6.0m` from config. But the **server's annotation code** (`server.py` L241–248) ignores the Decision Engine thresholds entirely and hardcodes its own `0.8 / 1.5 / 2.5` values. This means:

- An object at 1.9m will get a **red "URGENT" bounding box** on screen (server hardcode) but be classified as **INFO** by the Decision Engine (config says urgent < 2.0m, but the object is *almost* at the threshold so it might be warning).
- Actually worse: config says urgent < 2.0m, so 1.9m IS urgent in the engine. But an object at 0.9m gets "urgent" color on screen AND urgent in the engine — but for completely different threshold reasons. The visual feedback and the voice alert are not driven by the same thresholds.

**Why it matters:**  
The visual annotation and the voice alert are desynchronised. What looks urgent on screen might be classified differently by the engine.

**Proposed fix:**  
Remove all hardcoded thresholds from `server.py` and `main.py`. Have them query `decision_engine.urgent_threshold` / `decision_engine.warning_threshold` directly.

---

### CRIT-3: Naming Confusion — "Claude" vs "Groq"

**Files:**  
- `modules/claude_client.py` — class is named `ClaudeClient`, file is `claude_client.py`  
- But it actually uses `from groq import Groq` (line 180) and `GROQ_API_KEY` (line 173)  
- `config.yaml` line 100–106: section is named `groq`  
- `README.md` line 5: mentions "Claude claude-opus-4-6"  
- CLI flag is `--no-groq` (main.py line 83) but README says "Claude features"  

**The Problem:**  
The codebase is a confusing mix of two different AI provider names. The file, class, and some docs say "Claude" (Anthropic), but the actual implementation uses **Groq** with **LLaMA 4 Scout 17B**. This is not a functional bug but creates serious confusion for anyone reading or evaluating the project.

**Why it matters:**  
For a class project, this looks like the code was initially written for Claude and hastily migrated to Groq, but the renaming was incomplete. A reviewer will see contradictions.

**Proposed fix:**  
Pick one and be consistent. Since the actual API is Groq, rename `claude_client.py` → `llm_client.py`, `ClaudeClient` → `LLMClient`, and update all references.

---

## 🟠 Major Issues

### MAJ-1: Groq Rate Limits and Model Overkill

**File:** `modules/claude_client.py` line 155, `config.yaml` line 102  
**Model:** `meta-llama/llama-4-scout-17b-16e-instruct`

**The Problem:**  
- Groq's free tier has strict rate limits (typically 30 req/min for large models, sometimes less).
- The model is 17B parameters with 16 experts — this is overkill for generating 2-sentence navigation descriptions.
- The `auto_trigger_interval` is 30 seconds, meaning roughly 2 API calls per minute, which *seems* safe but becomes problematic when combined with manual 'D' key presses.
- There is **no rate limiting logic** in the code. If a user spams 'D', every press fires a new API call in a new thread.
- There is **no retry/backoff** on rate-limit errors (HTTP 429). The code catches all exceptions generically (line 296–298) and just speaks "Scene description unavailable."

**Why it matters:**  
The system will silently degrade when rate-limited, with no way for the user to know why descriptions stopped working.

**Proposed fix directions:**  
- Add a minimum interval between API calls (e.g., 10s cooldown on manual triggers too)
- Add retry with exponential backoff for 429 responses  
- Consider running a local model (e.g., Qwen3-VL-4B via LM Studio's OpenAI-compatible API) to eliminate rate limits entirely
- Even a 0.8B model generating 2 sentences would be sufficient for this use case

---

### MAJ-2: MiDaS Depth Estimation Accuracy Is Questionable

**Files:** `modules/depth_estimator.py`, `utils/calibration.py`

**The Problem:**  
Monocular depth estimation from a single 2D image is fundamentally **scale-ambiguous**. MiDaS outputs *relative* depth (closer things get higher values), but has no concept of absolute distance. The calibration formula:

```
distance_m = scale / (depth_value + offset)    # scale=2.0, offset=0.2
```

This is a simple inverse mapping with two hand-tuned constants. Issues:

1. **No camera-specific calibration.** Different webcams have different focal lengths and FoVs. The same object at 1m will produce different depth values on different cameras. The hardcoded `scale=2.0, offset=0.2` is only valid for whatever camera was used during tuning.
2. **No dynamic recalibration.** If the camera angle changes (user tilts laptop), all depth estimates shift.
3. **MiDaS Small is the least accurate model.** The config uses `MiDaS_small` for speed, but it has significantly lower accuracy than `DPT_Large` or `DPT_Hybrid`. On typical benchmarks, MiDaS Small has ~30% more depth error.
4. **Frame-level normalisation destroys absolute depth.** In `depth_estimator.py` lines 116–121, the depth map is normalised per-frame to [0,1]. This means if only one object is visible, it always gets depth ≈ 1.0 (closest) regardless of actual distance. The calibration then converts this to `2.0 / (1.0 + 0.2) = 1.67m` — even if the object is 10m away.

**Why it matters:**  
False distance estimates can cause:
- **False URGENT alerts** for distant objects (single-object frames)
- **Missed URGENT alerts** for genuinely close objects in crowded scenes

**Proposed fix directions:**  
- Switch normalisation from per-frame min/max to a fixed reference range
- Add a calibration mode where the user holds a known object at a known distance
- Consider using Depth Anything V2 (more accurate, similar speed) as an alternative to MiDaS

---

### MAJ-3: Tracker Is Not Actually ByteTrack

**File:** `modules/tracker.py` — docstring says "ByteTrack", code does IoU matching

**The Problem:**  
The README, docstrings, and architecture diagram all claim the system uses **ByteTrack** (a well-known multi-object tracking algorithm). But the actual implementation (`tracker.py` lines 53–152) is a **simple greedy IoU matcher**:

```python
for det in detections:
    best_track_id = None
    best_iou = 0.3
    for tid, state in self._track_state.items():
        iou = self._compute_iou(det["bbox"], state["bbox"])
        if iou > best_iou:
            best_iou = iou
            best_track_id = tid
```

This is a basic nearest-neighbour assignment. Real ByteTrack:
- Uses a Kalman filter for motion prediction
- Has two-stage association (high-confidence first, then low-confidence)
- Handles occlusion recovery
- Uses the Hungarian algorithm for optimal assignment

The current greedy approach will:
- **Swap IDs** when two objects cross paths (the greedy loop has no globally optimal assignment)
- **Lose tracks** during brief occlusions
- **Create duplicate IDs** when objects re-appear after being lost

**Why it matters:**  
ID swaps cause the cooldown to reset, leading to repeated alerts for the same object. Lost tracks mean the system "forgets" a dangerous object and then re-announces it from scratch after 5 frames.

**Proposed fix directions:**  
- Use Ultralytics' built-in `.track()` method instead of `.predict()` (it includes real ByteTrack/BoT-SORT)
- Or implement Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) for optimal IoU matching
- Add Kalman filter for motion prediction

---

### MAJ-4: pyttsx3 Re-initialised Every Single Utterance

**File:** `modules/voice.py` lines 177–195

**The Problem:**
```python
def _speak_english(self, text: str):
    engine = pyttsx3.init()          # NEW ENGINE EVERY TIME
    engine.setProperty("rate", ...)
    engine.say(text)
    engine.runAndWait()
    engine.stop()
```

The code creates, configures, uses, and destroys a new `pyttsx3` engine for **every single spoken sentence**. The comment says this is to work around "the Windows SAPI5 bug where `runAndWait()` silently stops working."

Issues:
- **Linux doesn't have the SAPI5 bug.** This workaround is Windows-specific but is applied unconditionally.
- **Each `pyttsx3.init()` takes 100–500ms** depending on the system. For urgent alerts, this adds critical latency.
- **The old engines are not properly garbage collected** — `engine.stop()` doesn't release the SAPI COM object on Windows.

**Why it matters:**  
Urgent safety alerts are delayed by the engine initialisation overhead.

**Proposed fix:**  
- Keep a persistent engine on Linux (check `sys.platform`)
- Only re-init on Windows, and only if `runAndWait()` fails
- Consider `edge-tts` (already mentioned in requirements.txt as a comment) which is faster and better quality

---

### MAJ-5: Hindi TTS Requires Internet (Safety Concern)

**File:** `modules/voice.py` lines 197–237

**The Problem:**  
Hindi speech uses `gTTS` (Google Text-to-Speech), which makes an HTTP request to Google's servers for every utterance:

```python
tts = gTTS(text=text, lang="hi")
tts.save(filename)           # HTTP request to Google
pygame.mixer.music.load(filename)
pygame.mixer.music.play()
```

This means:
- **No internet = no Hindi alerts.** The fallback (line 202) is to speak the Hindi text with the English engine, which produces gibberish.
- **Latency:** Each gTTS call takes 500ms–2s depending on network conditions. For an urgent "STOP!" alert, this is unacceptable.
- **Privacy:** Every spoken alert is sent to Google's servers as plain text.

**Why it matters:**  
A visually impaired user who has chosen Hindi mode expects timely alerts. If the internet drops, they get no Hindi alerts and no warning that the fallback is garbage.

**Proposed fix directions:**  
- Use `pyttsx3` with an Indic voice pack (e.g., `espeak-ng` supports Hindi)
- Use `edge-tts` with Hindi voice (marked as commented-out in requirements.txt)
- Pre-cache common alert phrases as MP3s for instant offline playback

---

## 🟡 Significant Issues

### SIG-1: No Vertical/Elevation Awareness

**Related to CRIT-1**

**The Problem:**  
The system only tracks horizontal position (left/center/right). It has **zero vertical awareness**. This means:
- A hanging sign at head height → same alert as a floor obstacle
- A step/curb → no "step down" warning
- An overhanging branch → "person ahead" (if misclassified) with no height context
- The user cannot distinguish "obstacle on the ground ahead" from "object overhead"

**Why it matters:**  
For navigation, vertical position is as critical as horizontal. A user needs to know whether to step over, duck under, or walk around.

---

### SIG-2: No Path Clearance Assessment

**The Problem:**  
The system tells you *what* objects are nearby, but never tells you the **most important thing**: *"Is it safe to keep walking forward?"*

There is no concept of:
- "The path directly ahead is clear for the next 3 metres"
- "You are in a narrow corridor"
- "There is a gap between the chair and the wall you can walk through"

The Groq scene description sometimes mentions path clearance ("path seems clear"), but this:
- Only runs every 30 seconds
- Has 1–3s latency
- Can hallucinate

**Why it matters:**  
Absence of information is dangerous. Silence from the system currently means either "nothing detected" OR "everything is too far away to care." The user can't tell which.

**Proposed fix:**  
Add periodic "path clear" announcements (e.g., every 10s if no obstacles detected center-forward within 3m).

---

### SIG-3: No Motion/Velocity Estimation

**The Problem:**  
The tracker assigns IDs but doesn't compute velocity vectors. The system cannot distinguish:
- A **parked car** vs. a **car driving toward the user**
- A **stationary person** vs. a **person walking toward the user**

Both get the same alert based purely on current distance.

**Why it matters:**  
A car at 4m moving toward you at 5m/s gives you < 1 second. A car at 4m that's parked gives you as much time as you need. The urgency is completely different.

**Proposed fix:**  
- Compute `Δdistance / Δtime` from the tracker's distance history
- If an object is approaching (negative velocity), escalate the alert level
- Add "approaching" / "moving away" to voice alerts

---

### SIG-4: Frame Resolution Is Very Low (320×240)

**File:** `config.yaml` lines 8–9

**The Problem:**  
The default camera resolution is `320×240` — this is QVGA, a resolution from the early 2000s. At this resolution:
- Small objects (bottles, curbs, steps) are only a few pixels wide
- YOLOv8 detection accuracy drops significantly below 640×480
- MiDaS depth estimation becomes noisier

The `min_bbox_area_ratio: 0.01` means an object must be at least `320×240×0.01 = 768 pixels²` (roughly 28×28 px). At 320×240, many real obstacles will be below this threshold until they're dangerously close.

**Why it matters:**  
Detection range is severely limited. The system won't see obstacles until they're very close, reducing reaction time.

**Proposed fix:**  
- Increase to at least 640×480 for detection
- If latency is a concern, process every Nth frame at high res and interpolate

---

### SIG-5: No Thread Safety on Shared Globals (Server Mode)

**File:** `server.py` lines 54–69

**The Problem:**  
The server uses global variables shared between the pipeline thread and async WebSocket tasks:

```python
latest_frame_b64 = ""        # Written by pipeline thread, read by async tasks
latest_telemetry = {}        # Same
alert_queue = asyncio.Queue()
connected_clients: set = set()
clients_lock = threading.Lock()  # Exists but not used for frame/telemetry!
```

`latest_frame_b64` and `latest_telemetry` are written from the pipeline thread and read from async coroutines with **no synchronisation**. In CPython, the GIL provides *some* protection for simple assignments, but:
- Dict mutations (`latest_telemetry = {...}`) can cause partially-read dicts in theory
- The `clients_lock` exists but is never actually used anywhere

**Why it matters:**  
Potential for corrupted telemetry data or partial frame reads, especially under high load.

---

### SIG-6: Dashboard Alert Queue Shared Incorrectly

**File:** `server.py` line 56, lines 540–545

**The Problem:**  
`alert_queue = asyncio.Queue()` is created at module level. The pipeline thread pushes to it via `loop.call_soon_threadsafe(alert_queue.put_nowait, ...)`. But in `_ws_send_loop`, **all connected clients** read from the **same queue**:

```python
while not alert_queue.empty():
    alert = alert_queue.get_nowait()
    await websocket.send_json(alert)
```

If two dashboard clients are connected, each alert is consumed by whichever client's send loop runs first. The other client never sees it.

**Why it matters:**  
Multi-client dashboard is broken — alerts are randomly distributed among connected clients instead of broadcast to all.

---

## 🔵 Minor Issues

### MIN-1: `_next_track_id()` Doesn't Handle ID Overflow

**File:** `modules/tracker.py` line 260–264

```python
def _next_track_id(self) -> int:
    if not self._track_state:
        return 1
    return max(self._track_state.keys()) + 1
```

If the system runs for extended periods with high object turnover, track IDs will grow unboundedly. Not a practical issue in short sessions, but for long-running server deployments, IDs could reach very large numbers.

---

### MIN-2: `frame_to_base64` Encodes at Quality 85 for API, 70 for WebSocket

**Files:**  
- `utils/frame_utils.py` line 169: `JPEG_QUALITY, 85` (for Groq API)
- `server.py` line 272: `JPEG_QUALITY, 70` (for WebSocket)

Two different quality levels for the same operation. The WebSocket one is fine (bandwidth savings). But the Groq API one at 85% may introduce JPEG artifacts that confuse the vision model.

---

### MIN-3: Temp Audio Files May Accumulate

**File:** `modules/voice.py` lines 212, 226–229

Hindi TTS creates temp MP3 files and attempts to delete them after playback. But if `pygame.mixer.music.unload()` or the playback loop crashes, the file won't be deleted. The cleanup in `stop()` only runs on graceful shutdown.

---

### MIN-4: `import numpy` Inside Method Body

**File:** `modules/tracker.py` line 225

```python
def get_distance_variance(self, track_id: int) -> float:
    ...
    import numpy as np  # Imported inside method!
```

`numpy` is imported at the top level in every other file but imported inside this method. This adds ~0.1ms per call for the import cache lookup.

---

### MIN-5: Dashboard Doesn't Handle WebSocket Reconnection Gracefully

**File:** `dashboard/app.js` lines 124–130

The reconnection logic uses exponential backoff capped at 30 seconds. But there's no visual indication to the user about *when* the next reconnect attempt will happen, and no manual "Reconnect" button.

---

## ⚪ Enhancement Opportunities

### ENH-1: Local LLM for Scene Description

The user has local models available:
- `/home/vista/.lmstudio/models/unsloth/Qwen3.5-0.8B-GGUF/Qwen3.5-0.8B-Q8_0.gguf` — 0.8B text model
- `/home/vista/.lmstudio/models/mradermacher/Qwen3-VL-4B-Instruct-GGUF/Qwen3-VL-4B-Instruct.Q5_K_S.gguf` — 4B vision-language model

Running the scene description through LM Studio's OpenAI-compatible local server would:
- Eliminate rate limits entirely
- Keep all data local (privacy)
- The 4B VL model can actually process the camera frame image directly
- Trade-off: slower inference (1–5s on GPU) vs. cloud, but no rate-limit failures

### ENH-2: Obstacle Avoidance Suggestions

Currently: "Chair ahead" — tells the user *what* but not *what to do*.
Better: "Chair ahead, move slightly left to avoid" — requires spatial reasoning about free space.

### ENH-3: Haptic Feedback Support

Voice alerts have inherent latency (speech takes time to hear). Adding haptic patterns (vibration via connected device) for URGENT alerts would provide near-instant feedback.

### ENH-4: Audio Beep Tones for Proximity

In addition to voice, proximity-based audio tones (faster beeping = closer) would give continuous spatial awareness without requiring speech processing.

### ENH-5: Recording / Logging for Post-Analysis

No detection or alert data is persisted. Adding a structured log (JSON lines per frame) would enable:
- Post-hoc analysis of false positives
- Calibration tuning with real-world data
- Benchmarking latency improvements

### ENH-6: Accessibility of the Dashboard Itself

The web dashboard is visual-only (ironically). Adding screen reader support, keyboard navigation, and audio readout of telemetry would make the monitoring interface accessible to visually impaired users or assistants.
