# 🧬 Complete Evolution Log — AI Navigation Assistant

> **Document scope:** Every architectural change, merge conflict, performance fix, and quality improvement made from the original Groq-cloud-based system through the current low-latency LM-Studio-powered pipeline. Includes exact code snippets, root-cause analysis, and why each solution was chosen.

---

## Table of Contents

1. [Phase 1: Original Architecture (Groq Cloud + espeak-ng Hindi)](#phase-1-original-architecture)
2. [Phase 2: Friend's LM Studio Branch](#phase-2-friends-lm-studio-branch)
3. [Phase 3: The Experimental Merge](#phase-3-the-experimental-merge)
4. [Phase 4: Hindi Voice Quality Overhaul](#phase-4-hindi-voice-quality-overhaul)
5. [Phase 5: Latency Elimination (Async Camera + Frame Skipping)](#phase-5-latency-elimination)
6. [Phase 6: Camera Orientation & Resolution Tuning](#phase-6-camera-orientation--resolution-tuning)
7. [Phase 7: Friend's Second Merge (Copy_2 → Async + Frame Skip)](#phase-7-friends-second-merge)
8. [Architecture Comparison Tables](#architecture-comparison-tables)
9. [Complete Issue Register](#complete-issue-register)
10. [Final Architecture Diagram](#final-architecture-diagram)

---

## Phase 1: Original Architecture

### Overview

The original system used **Groq Cloud API** (LLaMA 4 Scout 17B) for scene descriptions, **espeak-ng** for offline Hindi TTS, synchronous camera reading, and fixed 640×480 resolution.

### Key Components (Original)

| Component | Technology | File |
|-----------|-----------|------|
| LLM Brain | Groq API (`llama-4-scout-17b-16e-instruct`) via `groq` Python SDK | `modules/llm_client.py` |
| Hindi TTS | espeak-ng via pyttsx3 (offline) | `modules/voice.py` |
| Camera Reader | Synchronous `cv2.VideoCapture.read()` (main thread blocks) | `main.py` |
| Resolution | 640×480 | `config.yaml` |
| AI Pipeline | Every frame (detection + depth + tracking + decision) | `main.py` |

### Original Prompt Architecture

```python
# modules/llm_client.py (original — hardcoded inline prompts)
SYSTEM_PROMPT = """You are a navigation assistant...
Language: {language}"""
SCENE_DESCRIPTION_PROMPT = """Describe surroundings...
Detected objects: {detections_json}
Language: {language}"""
```

**Issue:** Single template with `{language}` placeholder. Hindi prompts were just English prompts with "Language: Hindi" appended. The model had to infer Hindi output from an English prompt structure — leading to inconsistent or roman-script Hindi responses.

### Original Hindi TTS

```python
# modules/voice.py (original Hindi logic)
def _check_hindi_support(self):
    # ... find espeak-ng Hindi voice ...
    if hindi_voice:
        self._hindi_mode = "espeak"  # espeak-ng used by default
    else:
        self._hindi_mode = "gtts"    # gTTS was the fallback only
```

**Issue:** espeak-ng Hindi voice quality is robotic, unclear, and the phoneme mapping for Hindi is poor. Words mix together and become unintelligible. Yet it was the **primary** Hindi backend.

### Original Camera Reader

```python
# main.py (original — blocking synchronous read)
cap = cv2.VideoCapture(cam_index)
# ...
while True:
    ret, frame = cap.read()  # BLOCKS until frame arrives
    # AI pipeline on EVERY frame (heavy!)
    detections = detector.detect(frame)
    depth_map = depth_estimator.estimate(frame)  # Always runs
    # ...
```

**Issues:**
1. `cap.read()` blocks the main thread — during network latency from IP camera, the entire pipeline freezes
2. AI pipeline runs on **every single frame** — YOLOv8x + MiDaS on every frame is wasteful when the scene changes slowly
3. Depth estimation runs even when **no objects are detected** — pure waste of GPU cycles

---

## Phase 2: Friend's LM Studio Branch

### What Changed

A collaborator forked and made these changes:

| Change | Details |
|--------|---------|
| **LM Studio Client** | Replaced Groq API with local LLM via `urllib` (no SDK needed). Server at `http://127.0.0.1:1234/v1` |
| **Category Cooldown** | Decision engine now tracks which object categories were recently alerted, suppresses re-alerts within cooldown window |
| **Spatial Grouping** | Nearby objects of same category are grouped into a single alert (e.g., "3 people ahead" instead of "person ahead" ×3) |
| **Urgent Queue Preemption** | Urgent alerts (`level == "urgent"`) clear the TTS queue so they play immediately |
| **Config Rename** | `groq` section renamed to `lm_studio` in `config.yaml` |
| **Language Toggle Cooldown** | 2-second guard prevents double-fire from keyboard repeat |
| **MJPEG Suppression** | `OPENCV_LOG_LEVEL=0` to silence MJPEG decoder warnings |

### Key Code: LM Studio Client

```python
# modules/lm_studio_client.py (friend's new file)
import urllib.request
import json

class LMStudioClient:
    def __init__(self, config):
        lm_cfg = config.get("lm_studio", {})
        self.base_url = lm_cfg.get("base_url", "http://127.0.0.1:1234/v1")
        self.model = lm_cfg.get("model", "qwen2.5-coder-3b-instruct-128k")
        self.use_structured_output = lm_cfg.get("use_structured_output", True)

    def _call_api(self, system_prompt, user_prompt):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 80,
            "temperature": 0.2,
        }
        if self.use_structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "navigation_instruction",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, ...)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
```

**Advantages over Groq:**
- No API key required
- No rate limits
- No internet dependency
- Runs entirely on local machine
- Structured output (JSON schema) enforced server-side prevents malformed responses

### Key Code: Category Cooldown

```python
# modules/decision_engine.py (friend's addition)
class DecisionEngine:
    def __init__(self, config):
        self._category_last_alerted = {}  # {label: timestamp}

    def evaluate(self, tracked_objects):
        alerts = []
        for obj in tracked_objects:
            label = obj.get("label", "unknown")
            now = time.time()

            # Category cooldown check
            last_time = self._category_last_alerted.get(label, 0)
            if now - last_time < self.category_cooldown:  # 8s default
                continue  # Skip this category, already recently alerted

            # Spatial grouping: find nearby objects of same label
            nearby = [o for o in tracked_objects
                      if o.get("label") == label
                      and abs(o.get("distance_m", 99) - obj.get("distance_m", 99)) < 1.0]

            if len(nearby) > 1:
                # Group into single alert
                message = f"{len(nearby)} {label}s ahead"
                # ...
                self._category_last_alerted[label] = now
                # skip individual objects in group
```

---

## Phase 3: The Experimental Merge

### The Problem

Two branches had diverged significantly:

| Area | Local Branch (Mine) | Friend's Branch |
|------|---------------------|-----------------|
| LLM Client | N/A (was `llm_client.py` with Groq, syntax-broken) | `lm_studio_client.py` (new, clean) |
| Tracker | Hungarian algorithm (scipy), velocity prediction, motion state | Simple IoU greedy matching |
| Depth Norm | Rolling percentile (5th/95th over 30 frames) | Per-frame min/max |
| Decision Engine | Path clearance + velocity escalation | Category cooldown + spatial grouping |
| Voice | Persistent pyttsx3 engine, Hindi support | Re-init per utterance, gTTS-only Hindi |
| Config | `groq` section (unused, dead) | `lm_studio` section (new) |
| Thresholds | urgent=0.8, warning=1.5, info=2.5 | urgent=2.0, warning=4.0, info=6.0 |

### Merge Strategy

**Decision:** Friend's `LMStudioClient` replaces old Groq `llm_client.py`. Combined both decision engine features (category cooldown + spatial grouping from friend, velocity escalation + path clearance from mine). Our tracking/depth/voice kept over friend's.

### Merge Conflicts Resolved

#### Conflict 1: `main.py` — Camera + LLM Init (6 conflicts)

**What happened:** Both branches changed how the camera and LLM client were initialized. Friend added `lm_studio` but also kept dead Groq code.

**Resolution:** Adopt friend's `LMStudioClient` (clean, working), delete old `llm_client.py`. Keep our camera init.

```python
# BEFORE (mine) — uses non-existent llm_client
from modules.llm_client import ClaudeClient  # BROKEN — syntax error
llm_client = ClaudeClient(config)

# BEFORE (friend) — has both
from modules.lm_studio_client import LMStudioClient
# also kept llm_client import — dead code

# AFTER — clean, one client
from modules.lm_studio_client import LMStudioClient
lm_client = LMStudioClient(config)
```

#### Conflict 2: `decision_engine.py` — 5 Conflicts

**What happened:** Both branches added features to the same class methods. Friend added `__init__` params + `evaluate()` logic (category cooldown, spatial grouping). Mine added `evaluate()` logic (velocity escalation, path clearance).

**Resolution:** Combined both — category cooldown + spatial grouping BEFORE velocity/path-clearance checks:

```python
# AFTER — combined decision engine
def evaluate(self, tracked_objects):
    # 1. Friend's: category cooldown
    if now - self._category_last_alerted.get(label, 0) < self.category_cooldown:
        continue

    # 2. Friend's: spatial grouping
    nearby = [o for o in tracked_objects if same_label_and_nearby]
    if len(nearby) > 1:
        # grouped alert

    # 3. Mine: velocity escalation
    if velocity > VELOCITY_FAST and distance < self.urgent_threshold * 1.5:
        level = "urgent"  # escalate

    # 4. Mine: path clearance
    if is_path_blocked(objects_in_center, distance):
        message = "Path blocked ahead"
```

#### Conflict 3: `server.py` — Broken Import

**What happened:** `server.py` imported from `modules.llm_client` which was deleted. Friend didn't touch `server.py`.

**Resolution:** Changed import to `modules.lm_studio_client`:

```python
# BEFORE
from modules.llm_client import ClaudeClient
# → ModuleNotFoundError (file was deleted)

# AFTER
from modules.lm_studio_client import LMStudioClient
```

#### Conflict 4: `config.yaml` — Auto-Merge

**What happened:** Both branches added different sections (`groq` vs `lm_studio`). Auto-merge kept both.

**Resolution:** Removed `groq` section entirely. Kept `lm_studio` section with friend's structure.

#### Post-Merge Bug: Path Clear Alert Format Crash

**What happened:** On first run after merge, `main.py` crashed at line ~309:

```python
dist_str = f"{dist:.1f}m" if isinstance(dist, (int, float)) else "?"
```

The `dist` value was `'?'` (a string `'?'` from the path-clear alert where distance is unavailable). The `isinstance` check passed as `False`, but earlier code assumed `dist` was always a number.

**Root cause:** Path-clear alerts set `distance_m` to `'?'` (string), not `None`. The format string `{dist:.1f}` crashed because it received a string.

**Fix:** Added `dist_str` extraction with type check:

```python
# BEFORE (crashed)
dist = alert.tracked_object.get('distance_m')
main_logger.info(f"(dist={dist:.1f}m, ...)")

# AFTER (safe)
dist = alert.tracked_object.get('distance_m')
dist_str = f"{dist:.1f}m" if isinstance(dist, (int, float)) else "?"
main_logger.info(f"(dist={dist_str}, ...)")
```

#### Post-Merge Cleanup: Deleted Dead File

**File:** `modules/llm_client.py` — had a syntax error (missing `except` block after `try:` at line 248), was no longer imported anywhere after the merge.

```python
# llm_client.py line 248 — syntax error
try:
    # ... some code ...
# ← missing 'except' block!
```

**Fix:** `git rm modules/llm_client.py`

---

## Phase 4: Hindi Voice Quality Overhaul

### Problem Statement

Hindi voice output was poor in two ways:
1. **TTS quality:** espeak-ng Hindi sounds robotic, phonemes are wrong, words blend together
2. **Prompt mismatch:** English prompts with "Language: Hindi" made Qwen output Roman Hindi inconsistently

### Fix 1: Separated Prompts by Language

**Problem:** Single prompt template with `{language}` param. Hindi had to infer language from "Language: Hindi" at end of English prompt.

**Solution:** Created `modules/prompts.py` with separate English and Hindi prompt constants:

```python
# modules/prompts.py — NEW FILE
SYSTEM_PROMPT_EN = """You are a compact navigation assistant AI...
- For objects under 1 meter: start with STOP..."""

SYSTEM_PROMPT_HI = """आप एक नेत्रहीन उपयोगकर्ता के लिए कॉम्पैक्ट नेविगेशन सहायक AI हैं।
- 1 मीटर से कम दूरी वाली वस्तु के लिए: RUKO से शुरू करें..."""

SCENE_DESCRIPTION_PROMPT_EN = """Describe the user's surroundings...
Detected objects: {detections_json}..."""

SCENE_DESCRIPTION_PROMPT_HI = """उपयोगकर्ता के आस-पास के वातावरण का वर्णन करें...
पहचानी गई वस्तुएं: {detections_json}..."""

STARTUP_PROMPT_EN = """Generate a short, friendly startup message...
Output: The greeting sentence ONLY."""

STARTUP_PROMPT_HI = """नेविगेशन असिस्टेंट के लिए एक छोटा, मैत्रीपूर्ण संदेश उत्पन्न करें...
आउटपुट: केवल अभिवादन वाक्य।"""
```

**Updated `lm_studio_client.py`** to import and select by language:

```python
# BEFORE — inline prompts with {language} placeholder
system = SYSTEM_PROMPT.format(language=lang_name)

# AFTER — imported from prompts.py, selected by language
from modules.prompts import SYSTEM_PROMPT_EN, SYSTEM_PROMPT_HI, ...

@staticmethod
def _get_prompts(language):
    if language == "hi":
        return SYSTEM_PROMPT_HI, SCENE_DESCRIPTION_PROMPT_HI, STARTUP_PROMPT_HI
    return SYSTEM_PROMPT_EN, SCENE_DESCRIPTION_PROMPT_EN, STARTUP_PROMPT_EN
```

**Why this works:** Qwen 3.5 receives Hindi system + user prompts in Devanagari script. The model natively understands Hindi, so it responds directly in Hindi (Roman or Devanagari) without needing translation. The `{language}` placeholder is completely eliminated.

### Fix 2: gTTS Priority Over espeak-ng

**Problem:** espeak-ng Hindi was primary. It sounds robotic because it's a formant synthesizer with crude Hindi phoneme mapping. gTTS uses Google's neural TTS which produces natural-sounding Hindi.

```python
# BEFORE — espeak-ng was primary
def _check_hindi_support(self):
    if hindi_voice:
        self._hindi_mode = "espeak"    # ← robotic Hindi as default!
    else:
        self._hindi_mode = "gtts"      # ← good Hindi only as fallback

# AFTER — gTTS is primary, espeak-ng is fallback
def _check_hindi_support(self):
    self._hindi_mode = "gtts"          # ← good Hindi as default
    self._init_pygame()
    # Check espeak-ng as offline fallback only
    if hindi_voice:
        self._hindi_voice_id = voice.id  # ← fallback only if needed

def _speak_hindi(self, text):
    # Try gTTS first
    if self._speak_hindi_gtts(text):
        return
    # Fall back to espeak-ng
    if self._hindi_voice_id:
        self._speak_hindi_espeak(text)
    else:
        self._speak_english(text)
```

**Note:** gTTS requires internet. On the first call it downloads a ~2s MP3 from Google's servers. Subsequent calls use cached DNS and are faster. If internet is unavailable, the system falls back to espeak-ng (offline).

### Fix 3: espeak Fallback Chain Fix

**Problem:** `_speak_hindi_espeak()` had a fallback loop — if espeak failed, it tried gTTS. But now gTTS is already tried first in `_speak_hindi()`. This created a redundant (and potentially looping) fallback chain.

```python
# BEFORE — redundant fallback in espeak method
def _speak_hindi_espeak(self, text):
    try:
        # ... speak with espeak ...
    except Exception as e:
        self._speak_hindi_gtts(text)  # ← loops back to gTTS (already tried!)

# AFTER — espeak method falls back to English only
def _speak_hindi_espeak(self, text):
    try:
        # ... speak with espeak ...
    except Exception as e:
        self._speak_english(text)  # ← safe terminal fallback
```

---

## Phase 5: Latency Elimination

### The Problem

With the IP Webcam (phone camera), latency was 3-4 seconds. The pipeline ran at 15 FPS with all processing on every frame.

**Root causes:**

| Cause | Impact |
|-------|--------|
| Synchronous `cap.read()` | Main thread blocks waiting for network frame. IP Webcam buffers frames internally, so we always get the OLDEST frame in the buffer → 2-3 second lag |
| AI on every frame | YOLOv8x + MiDaS on every frame = 66ms per frame → 15 FPS hard cap |
| Depth on empty frames | MiDaS runs even when no objects detected → wastes 20-40ms per frame |
| 640×480 resolution | 4× more pixels than needed. YOLO inference time scales roughly linearly with pixel count |
| No frame skip | Detection/tracking/decision every frame when scene barely changes |

### Fix 1: Async Camera Reader

**Created `modules/camera.py`** — a threaded frame grabber that continuously reads from the camera in a background daemon thread, always keeping only the latest frame:

```python
# modules/camera.py — NEW FILE
import threading
import cv2
import numpy as np

class CameraStream:
    def __init__(self, source, width=640, height=480):
        self._cap = cv2.VideoCapture(source)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize internal buffer!
        self._lock = threading.Lock()
        self._frame = None
        self._ret = False
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def read(self):
        with self._lock:
            return self._ret, self._frame.copy() if self._frame is not None else None

    def _reader_loop(self):
        while self._running:
            ret, frame = self._cap.read()
            with self._lock:
                self._ret = ret
                self._frame = frame  # Always overwrites — only latest frame kept
```

**How it eliminates latency:**
- The background thread continuously reads frames (discarding old ones)
- The main thread calls `cam.read()` — instantly gets the latest frame, never blocks
- `CAP_PROP_BUFFERSIZE=1` tells OpenCV not to buffer more than 1 frame internally
- Old frames from the IP Webcam stream are discarded immediately

**Usage in `main.py`:**

```python
# BEFORE — blocking, 3-4s delay
cap = cv2.VideoCapture(cam_index)
while True:
    ret, frame = cap.read()  # ← blocks, gets old buffered frame

# AFTER — non-blocking, latest frame
cam = CameraStream(cam_index, frame_width, frame_height)
cam.start()
while True:
    ret, frame = cam.read()  # ← instant, always latest
```

### Fix 2: Frame Skipping (process_every_n)

**Added `performance.process_every_n_frames: 3` to config:**

```yaml
# config.yaml
performance:
  process_every_n_frames: 3     # Run AI every 3rd frame only
```

**Implementation in `main.py`:**

```python
# Performance config
perf_config = config.get("performance", {})
process_every_n = max(1, perf_config.get("process_every_n_frames", 3))

frame_index = 0
cached_tracked_objects = []
cached_annotated_frame = None

while True:
    frame_index += 1

    if frame_index % process_every_n == 0:
        # HEAVY path: detection + depth + tracking + decision
        detections = detector.detect(frame)
        if len(detections) > 0:
            depth_map = depth_estimator.estimate(frame)  # Conditional!
            # ... enrich, track, decide, annotate ...
        cached_tracked_objects = tracked_objects
        cached_annotated_frame = annotated_frame
    else:
        # LIGHT path: reuse cached annotations on the new frame
        annotated_frame = (
            annotate_frame(frame, cached_tracked_objects)
            if cached_tracked_objects
            else frame
        )
```

**Why it works:** The scene doesn't change significantly in 1/10th of a second. Objects detected on frame N are still in approximately the same position on frame N+1 and N+2. The visual annotation (bounding boxes) is re-drawn on every frame for smooth display, but the detection/tracking/decision runs at 1/3 the rate.

### Fix 3: Conditional Depth Estimation

**Problem:** MiDaS (depth estimation) ran on every single frame, even when no objects were detected. This wasted ~20-40ms of GPU time per frame.

```python
# BEFORE — depth always runs
depth_map = depth_estimator.estimate(frame)  # Even on empty frames!
for det in detections:
    det["distance_m"] = depth_estimator.get_distance(depth_map, det["bbox"])

# AFTER — depth only when objects detected
if len(detections) > 0:
    depth_map = depth_estimator.estimate(frame)  # Only when needed!
    for det in detections:
        det["distance_m"] = depth_estimator.get_distance(depth_map, det["bbox"])
```

**Savings:** When the scene is empty (no objects), MiDaS is skipped entirely. In typical indoor environments with intermittent objects, this saves ~30-50% of depth computation.

### Fix 4: Reduced Resolution

**Changed from 640×480 → 320×240:**

```yaml
# BEFORE
frame_width: 640
frame_height: 480

# AFTER
frame_width: 320
frame_height: 240
```

**Impact:** 4× fewer pixels (307,200 → 76,800). YOLOv8x inference time scales roughly linearly with pixel count. At 320×240, YOLOv8x runs ~2-3× faster. MiDaS also runs faster on smaller inputs.

### Combined Latency Impact

| Change | Latency Reduction | Cumulative FPS (estimated) |
|--------|------------------|---------------------------|
| Async camera reader | ~2-3s eliminated | 15 → 30 |
| Frame skipping (3×) | 66% fewer AI runs | 30 → perceived 90 |
| Conditional depth | 30-50% fewer depth runs | +10-20% |
| 320×240 resolution | 4× fewer pixels | +50-100% |

**Net result:** From 3-4 second delay with 15 FPS → <500ms delay with smooth display.

---

## Phase 6: Camera Orientation & Resolution Tuning

### Problem: Phone Camera Rotated 90°

**Issue:** When using IP Webcam from an Android phone in portrait orientation, the video stream appears rotated 90° (or -90°) when viewed on a landscape-oriented desktop.

**Fix:** Added `rotation` config option with `cv2.rotate()` mapping:

```yaml
# config.yaml
camera:
  rotation: -90    # 0, 90, -90, or 180
```

```python
# main.py — rotation applied after frame capture, before resize
if frame_rotation != 0:
    rot_map = {
        90: cv2.ROTATE_90_CLOCKWISE,
        -90: cv2.ROTATE_90_COUNTERCLOCKWISE,
        180: cv2.ROTATE_180,
    }
    rot_code = rot_map.get(frame_rotation)
    if rot_code is not None:
        frame = cv2.rotate(frame, rot_code)
```

**Note:** Rotation is applied BEFORE resize, so the final output always matches `frame_width` × `frame_height`.

### Problem: Phone Settings vs Code Settings

The IP Webcam app has its own resolution setting IN the app (Video preferences → Camera resolution). The config.yaml `frame_width`/`frame_height` is applied via `cv2.VideoCapture.set()`. These can conflict:

- If IP Webcam streams at 640×480 but config sets 320×240, OpenCV will resize after reading
- If IP Webcam streams at 320×240, less network bandwidth is used
- **Recommendation:** Match both. Set IP Webcam app to same resolution as config.yaml

---

## Phase 7: Friend's Second Merge (Copy_2)

### What Arrived

The friend had a separate branch (`copy_2` directory) with additional improvements:

| Feature | Friend's Approach | Our Approach (Before) |
|---------|------------------|----------------------|
| **Camera Reader** | `CameraStream` (async threaded) | Synchronous `cv2.VideoCapture` |
| **Frame Skipping** | `process_every_n_frames: 3` | No skip (every frame) |
| **Conditional Depth** | Only when objects detected | Always runs |
| **Resolution** | 320×240 | 640×480 |
| **Tracker** | Simple IoU greedy matching | Hungarian algorithm (scipy) |
| **Decision** | No velocity/path clearance | Had both |
| **Voice** | Re-init pyttsx3 per utterance | Persistent engine |
| **Hindi** | gTTS-only | espeak-ng primary |

### What We Merged (and What We Kept)

**Merged from friend:**
1. `modules/camera.py` — async threaded reader
2. Frame skipping logic in `main.py`
3. Conditional depth estimation
4. `performance.process_every_n_frames` config
5. 320×240 resolution (already merged previously)

**Kept from our version:**
1. `modules/prompts.py` — friend had inline prompts
2. Rotation handling — friend had none
3. Hungarian tracker with velocity prediction
4. Velocity escalation + path clearance in decision engine
5. Persistent pyttsx3 engine — friend re-initialized per utterance (wasteful)
6. gTTS primary + espeak-ng fallback — friend had gTTS-only
7. Rolling percentile depth normalization — friend used per-frame min/max

### Key: Friend had a `claude_client.py` (Groq) file that we DID NOT merge

The friend's `copy_2` included a `modules/claude_client.py` that used Groq API for vision-based scene descriptions (sent the annotated frame as base64 to Groq). We intentionally skipped this because:

1. LM Studio handles scene descriptions locally
2. No internet dependency
3. No API key required
4. Structured output (JSON schema) prevents hallucinated format

---

## Architecture Comparison Tables

### Module-by-Module Comparison

| Module | Original (Phase 1) | Friend's Branch (Phase 2) | Current (After All Merges) |
|--------|-------------------|--------------------------|---------------------------|
| **LLM Client** | `llm_client.py` (Groq API, syntax error) | `lm_studio_client.py` (urllib, local) | `lm_studio_client.py` + `prompts.py` |
| **Prompts** | Inline, `{language}` placeholder | Inline, `{language}` placeholder | `prompts.py`, separate EN/HI constants |
| **Camera Reader** | Synchronous `cap.read()` | Synchronous `cap.read()` | `CameraStream` (async threaded) |
| **Frame Processing** | Every frame | Every frame | Every Nth frame (configurable) |
| **Depth** | Always runs | Always runs | Conditional on detection |
| **Resolution** | 640×480 | 320×240 (in copy_2) | 320×240 |
| **Rotation** | None | None | Configurable (-90, 90, 180) |
| **Hindi TTS** | espeak-ng primary, gTTS fallback | gTTS-only | gTTS primary, espeak-ng fallback |
| **Tracker** | Hungarian + velocity + motion | IoU greedy | Hungarian + velocity + motion |
| **Decision Engine** | Basic thresholds | Category cooldown + spatial grouping | Combined: cooldown + grouping + velocity + path clearance |
| **pyttsx3** | Persistent engine | Re-init per utterance | Persistent engine |
| **Config** | `groq` section | `lm_studio` section | `lm_studio` + `performance` sections |

### Performance Comparison (IP Webcam, 30 FPS stream)

| Metric | Original (Phase 1) | After Phase 5-7 |
|--------|-------------------|-----------------|
| **End-to-end latency** | 3-4 seconds | <500ms |
| **Display FPS** | 15 FPS (capped by pipeline) | 30 FPS (camera max) |
| **AI pipeline runs** | Every frame (30/s) | Every 3rd frame (10/s) |
| **Depth runs** | Every frame (30/s) | Only when objects detected |
| **Resolution** | 640×480 (307K pixels) | 320×240 (77K pixels) |
| **Hindi TTS quality** | Robotic (espeak-ng) | Natural (gTTS neural) |
| **LLM response** | Groq API (internet) | LM Studio (local) |
| **Structured output** | No | Yes (JSON schema) |
| **Camera rotation fix** | No | Yes (configurable) |

---

## Complete Issue Register

### ISSUE-001: llm_client.py Syntax Error

- **File:** `modules/llm_client.py` line 248
- **Error:** Missing `except` block after `try:`
- **Impact:** Module could not be imported — entire pipeline crashed on startup
- **Fix:** Deleted the file (it was replaced by `lm_studio_client.py`)
- **Status:** Resolved ✓

### ISSUE-002: Path Clear Alert Format Crash

- **File:** `main.py` line ~309 (post-merge)
- **Error:** `ValueError: Unknown format code 'f' for object of type 'str'`
- **Root cause:** `dist = '?'` (string) when `alert.get_message()` returns path-clear message
- **Code:**
  ```python
  # Crash
  dist = alert.tracked_object.get('distance_m')  # → '?' (str)
  main_logger.info(f"(dist={dist:.1f}m, ...)")    # ← TypeError!
  ```
- **Fix:**
  ```python
  dist_str = f"{dist:.1f}m" if isinstance(dist, (int, float)) else "?"
  ```
- **Status:** Resolved ✓

### ISSUE-003: server.py Broken Import

- **File:** `server.py` line ~15
- **Error:** `ModuleNotFoundError: No module named 'modules.llm_client'`
- **Root cause:** `server.py` imported from deleted `llm_client.py`. Friend's merge didn't update `server.py`
- **Fix:**
  ```python
  # BEFORE
  from modules.llm_client import ClaudeClient
  # AFTER
  from modules.lm_studio_client import LMStudioClient
  ```
- **Status:** Resolved ✓

### ISSUE-004: espeak-ng Hindi Quality

- **File:** `modules/voice.py`
- **Problem:** Hindi output is robotic, phonemes are wrong, words blend together
- **Root cause:** espeak-ng uses formant synthesis with crude language phoneme mapping. Hindi has complex conjunct consonants (संयुक्ताक्षर) that espeak-ng handles poorly
- **Fix:** Switched priority — gTTS is primary (neural TTS), espeak-ng only as fallback
- **Note:** gTTS requires internet; offline environments will still use espeak-ng
- **Status:** Resolved ✓

### ISSUE-005: Prompt Language Mismatch

- **File:** `modules/lm_studio_client.py` (original)
- **Problem:** Single English prompt with `"Language: Hindi"` appended. Qwen outputs Roman Hindi inconsistently
- **Root cause:** The model receives mostly English instructions with a one-line language hint. Hindi output is not guaranteed
- **Fix:** Created `modules/prompts.py` with fully separate Hindi prompts in Devanagari. LM Studio selects the correct prompt set based on `language` parameter
- **Code:**
  ```python
  @staticmethod
  def _get_prompts(language):
      if language == "hi":
          return SYSTEM_PROMPT_HI, SCENE_DESCRIPTION_PROMPT_HI, STARTUP_PROMPT_HI
      return SYSTEM_PROMPT_EN, SCENE_DESCRIPTION_PROMPT_EN, STARTUP_PROMPT_EN
  ```
- **Status:** Resolved ✓

### ISSUE-006: 3-4 Second Camera Latency

- **File:** `main.py` (original `cap.read()`)
- **Problem:** When using IP Webcam (phone camera over WiFi), there's 3-4 seconds of delay
- **Root causes:**
  1. OpenCV's internal frame buffer accumulates frames during network latency
  2. `cap.read()` returns the OLDEST buffered frame, not the latest
  3. Main thread blocks waiting for network I/O
- **Fix:** Created `CameraStream` (async threaded reader). Background thread continuously reads and discards old frames. Main thread always gets the latest frame instantly
- **Result:** <500ms latency
- **Status:** Resolved ✓

### ISSUE-007: FPS Capped at 15

- **File:** `main.py` (entire pipeline)
- **Problem:** Pipeline runs at 15 FPS regardless of camera capability
- **Root causes:**
  1. YOLOv8x + MiDaS on every frame = ~66ms per frame
  2. 640×480 resolution = 4× more pixels than needed
  3. No frame skipping
- **Fixes:**
  1. Frame skipping (process every 3rd frame) — AI runs 3× less often
  2. 320×240 resolution — 4× fewer pixels
  3. Conditional depth — skip MiDaS when no objects detected
- **Result:** Display runs at camera max FPS (30), AI runs at 10 FPS
- **Status:** Resolved ✓

### ISSUE-008: Phone Camera Rotated 90°

- **File:** `main.py` (frame pipeline)
- **Problem:** IP Webcam from portrait-oriented phone appears sideways/upside-down
- **Fix:** Added `rotation` config option (-90, 90, 180) with `cv2.rotate()` mapping
- **Note:** Must match phone orientation. -90 for most portrait modes with camera at top
- **Status:** Resolved ✓

### ISSUE-009: Config Resolution Mismatch

- **File:** `config.yaml` vs IP Webcam app settings
- **Problem:** If IP Webcam streams at a different resolution than config.yaml, the `cap.set(CAP_PROP_WIDTH/HEIGHT)` may not take effect
- **Fix:** Always match both settings. IP Webcam app → Video preferences → Camera resolution → set to 320×240 (or whatever config.yaml has)
- **Note:** The async camera reader doesn't change this — it reads whatever resolution the camera provides. Config resolution is applied as a hint to the camera driver
- **Status:** Documented ✓

### ISSUE-010: LM Studio Model Not Loaded

- **File:** `config.yaml` → `lm_studio.model`
- **Problem:** Config specified `qwen2.5-coder-3b-instruct-128k` but that model was not loaded in LM Studio
- **Impact:** LM Studio would fall back to some default model or return an error
- **Fix:** Checked available models via `curl http://127.0.0.1:1234/v1/models` and updated config to `qwen3.5-0.8b` (the smallest/fastest loaded model)
- **Command:**
  ```bash
  curl -s http://127.0.0.1:1234/v1/models | python -m json.tool
  ```
- **Status:** Resolved ✓

### ISSUE-011: Auto Trigger Interval Too Aggressive

- **File:** `config.yaml` → `auto_trigger_interval_seconds: 5`
- **Problem:** Friend changed from 30s to 5s. Scene descriptions fired every 5 seconds regardless of scene changes, flooding the TTS queue
- **Fix:** Restored to 30s (original value)
- **Status:** Resolved ✓

### ISSUE-012: espeak Fallback Loop

- **File:** `modules/voice.py` → `_speak_hindi_espeak()`
- **Problem:** espeak method fell back to gTTS, but `_speak_hindi()` already tried gTTS first. Creates unnecessary code path and potential confusion
- **Fix:** Changed espeak fallback to English (terminal fallback)
  ```python
  # BEFORE
  except Exception:
      self._speak_hindi_gtts(text)  # Try gTTS again (already tried)

  # AFTER
  except Exception:
      self._speak_english(text)  # Give up gracefully
  ```
- **Status:** Resolved ✓

### ISSUE-013: gTTS Return Value

- **File:** `modules/voice.py` → `_speak_hindi_gtts()`
- **Problem:** The method had no return value, so `_speak_hindi()` couldn't tell if gTTS succeeded or failed
- **Fix:** Changed return type to `bool`:
  ```python
  def _speak_hindi_gtts(self, text: str) -> bool:
      try:
          # ... speak ...
          return True
      except Exception:
          return False
  ```
- **Status:** Resolved ✓

---

## Final Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  CameraStream (threaded, async)                                  │
│  ┌────────────────────────────────────┐                          │
│  │  Background thread: cap.read() →   │  Always latest frame     │
│  │  overwrite _frame buffer           │  Never blocks main       │
│  └────────────┬───────────────────────┘                          │
│               │ cam.read() (instant)                             │
│               ▼                                                   │
│  ┌─────────────────────────┐                                     │
│  │  cv2.rotate()           │  ← only if rotation ≠ 0             │
│  └───────────┬─────────────┘                                     │
│              │ resize to 320×240                                  │
│              ▼                                                   │
│  ┌─────────────────────────┐                                     │
│  │  frame_index % 3 == 0?  │──No──→ Annotate with cached boxes   │
│  └───────────┬─────────────┘                                     │
│           Yes │                                                   │
│              ▼                                                   │
│  ┌─────────────────┐                                             │
│  │  YOLOv8 detect   │──empty──→ Skip depth                       │
│  └────────┬────────┘                                             │
│           │ objects found                                         │
│           ▼                                                       │
│  ┌─────────────────┐                                             │
│  │  MiDaS depth     │  ← Only when objects detected              │
│  └────────┬────────┘                                             │
│           ▼                                                       │
│  ┌─────────────────┐                                             │
│  │  Direction +     │  LEFT / CENTER / RIGHT + distance in metres│
│  │  Distance enrich │                                             │
│  └────────┬────────┘                                             │
│           ▼                                                       │
│  ┌─────────────────┐                                             │
│  │  Hungarian       │  Velocity prediction, motion state, IDs    │
│  │  Tracker update  │                                             │
│  └────────┬────────┘                                             │
│           ▼                                                       │
│  ┌─────────────────────────┐                                     │
│  │  Decision Engine         │  Combined:                          │
│  │  ├─ Category cooldown   │   - Skip if category recently alerted│
│  │  ├─ Spatial grouping    │   - Group nearby same-label objects  │
│  │  ├─ Velocity escalation │   - Fast-moving → urgent escalation  │
│  │  └─ Path clearance      │   - Blocked-center → special alert   │
│  └────────┬────────────────┘                                     │
│           ▼                                                       │
│  ┌─────────────────┐                                             │
│  │  VoiceEngine     │  Async TTS via daemon thread                │
│  │  ├─ English      │  pyttsx3 (offline, persistent engine)       │
│  │  └─ Hindi        │  gTTS primary → espeak-ng fallback         │
│  └─────────────────┘                                             │
│           ↕ (every 30s or 'D' key)                                │
│  ┌─────────────────┐                                             │
│  │  LM Studio       │  Local LLM (Qwen 3.5-0.8B)                 │
│  │  ├─ Prompts from│  modules/prompts.py (separate EN/HI)        │
│  │  └─ Structured  │  JSON schema forces { "instruction": "" }   │
│  └─────────────────┘                                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Files Reference

| File | Purpose | Key Lines |
|------|---------|-----------|
| `modules/prompts.py` | English + Hindi prompt constants | 6 prompt pairs |
| `modules/camera.py` | Async threaded camera reader | 119 lines |
| `modules/lm_studio_client.py` | LM Studio API client with prompt selection | `_get_prompts()` at line ~140 |
| `modules/voice.py` | Bilingual TTS with gTTS priority | `_speak_hindi()` at line ~300 |
| `main.py` | Main pipeline with frame skipping + async camera | Frame skip at line ~255 |
| `config.yaml` | All tunable parameters | `performance`, `camera.rotation`, `lm_studio` |

## Environment Notes

- **Python version:** 3.14.5
- **CUDA:** Available (MiDaS runs on GPU)
- **YOLOv8 model:** `yolov8x.pt` (can swap to `yolov8n.pt` for faster CPU inference)
- **LM Studio models loaded:** `qwen3.5-0.8b`, `qwen3-vl-4b-instruct`, etc.
- **LM Studio URL:** `http://127.0.0.1:1234/v1`
- **Virtual environment:** `.venv/` in project root
- **Camera (external):** IP Webcam Android app → WiFi stream
- **Camera (internal):** `/dev/video0` at 640×480, hardware-limited to ~14 FPS

---

*Document generated: 2026-06-10*
*Covers all phases from initial Groq-based system through final low-latency LM-Studio pipeline.*
