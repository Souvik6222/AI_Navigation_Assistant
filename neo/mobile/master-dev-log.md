# AI Navigation Assistant — Master Development Log

> **Purpose:** If someone is building this from scratch, this document tells them every trap, architectural mistake, and runtime bug discovered — in order from initial C++ port to live Android device testing. Do not skip sections. Each bug took hours to find.

Branch: `experimental-merge-arm` → `main`
App Location: `mobile/`
APK Target: `ai_navigation_assistant-v0.0.3-alpha.apk`

---

## Part 1 — Architecture Overview (C++ Port from Python)

The AI Navigation Assistant was originally a Python pipeline using `ultralytics`, `PyTorch`, `pyttsx3`, and `OpenCV`. This section explains why we ported it and what every file does.

### Why C++ at All?

**The Python bottleneck:** Even with a 20-core / 28-thread desktop CPU, the Python pipeline couldn't exceed 10 FPS.

**Root cause:** Python's Global Interpreter Lock (GIL) forces CPU-bound tasks (bbox iteration, depth region sampling, annotation drawing) onto a single thread. No amount of threading libraries can bypass it for CPU-bound work.

**The solution:** Full C++ rewrite using `ONNX Runtime C++ API` + `OpenCV C++`. This enables:
- True multithreading
- Zero-copy `cv::Mat` <-> ONNX tensor memory sharing
- JNI integration into Android (Python cannot do this)

---

## Part 2 — File-by-File Breakdown

### `mobile/include/types.hpp` — The Shared Data Blueprint

Defines the shared C++ structs that replace Python dicts:

```
Detection      → bbox, label, confidence, center_x/y, distance_m, direction
TrackedObject  → Detection + track_id, tracked_frames, should_announce, alert_level
Alert          → level, message_en, message_hi, priority_score, track_id
Config         → All settings (FPS, thresholds, paths) with defaults
```

**Critical to know about `Config`:**
```cpp
struct Config {
    float depth_scale = 2.0f;           // MiDaS raw → meters multiplier
    float urgent_threshold = 2.0f;      // < 2m → "very close"
    float warning_threshold = 4.0f;     // < 4m → "nearby"
    float info_threshold = 6.0f;        // < 6m → "ahead"
    float alert_cooldown_seconds = 7.0f;
    float path_clear_interval_seconds = 15.0f;
    int consecutive_frames_required = 3; // 3 frames before announcing
    int process_every_n_frames = 3;      // "Mode: skip" in logs = this
};
```

---

### `mobile/src/detector.cpp` — YOLOv8 via ONNX Runtime

- Loads `yolov8n_int8.onnx` via ONNX Runtime C++ API (no PyTorch dependency)
- Uses `cv::dnn::blobFromImage()` for preprocessing
- Applies NMS via `cv::dnn::NMSBoxes()`
- Filters detections by a configurable indoor `whitelist`

**YOLOv8 output is transposed!** Output shape is `[1, 84, 8400]` (features × detections), NOT `[1, 8400, 84]`. See Bug 5 below.

---

### `mobile/src/depth_estimator.cpp` — MiDaS Depth

- Loads `midas_v21_small_256.onnx`
- **Output is `CV_32F` with values `0.0 – 1.0`** — HIGH value = CLOSE, LOW = FAR (inverted!)
- Calibration: `distance = scale / (depth_value + offset)` → approximate meters
- Rolling 5th/95th percentile normalization prevents scene-change jumps

**CRITICAL:** Every wall detection bug came from not knowing this is float 0-1, not uint8 0-255.

---

### `mobile/src/tracker.cpp` — Object Tracker

- Greedy IoU matching (replaces Python's scipy Hungarian algorithm)
- EMA velocity smoothing: `vel = 0.3 * instant + 0.7 * prev`
- Alert suppression via per-object cooldown (default 7s)
- Motion classification: `APPROACHING` / `RECEDING` / `STATIONARY`

---

### `mobile/src/decision_engine.cpp` — Alert Generator

- Distance thresholds: `urgent < 2m`, `warning < 4m`, `info < 7m`
- Priority: closer = higher, CENTER > sides, approaching = +3
- Bilingual alerts: English + Hindi (hardcoded translations in `HINDI_LABELS` map)
- Smart deduplication: groups same class+direction → "3 people ahead"
- Path clear: fires every 15s if nothing blocking center zone

---

### `mobile/src/pipeline.cpp` — The Main Loop

```
push_frame() [called by CameraX via JNI every ~1s]
  → Rotate frame to portrait orientation
  → Center-crop to square
  → Resize to 640x640
  → Every 3rd frame (process_every_n_frames):
      depth_estimator.estimate() → depth_map [CV_32F, 0.0-1.0, HIGH=CLOSE]
      Wall check: if center-zone mean > 0.65, inject synthetic "wall" detection
      detector.detect() → Detections (YOLO)
      For each detection: get_direction(), get_distance(depth_map, bbox)
      tracker.update() → TrackedObjects
      decision_engine.evaluate() → Alerts
      alert_callback_(message, urgent) → JNI → speak() / speakUrgent()
  → visual_callback_(boxes) → JNI → OverlayView (drawn every frame)
  → Every 15s: scene_triggered_callback_(base64) → LLM API
```

---

### `mobile/android/src/com/navigation/assistant/MainActivity.java` — Android Shell

Three TTS methods — each with a different purpose and priority:

```java
speak(text)        // Regular nav alert. SKIPPED if LLM spoke < 8s ago.
speakUrgent(text)  // Urgent alert (wall, fast approach). ALWAYS fires. Resets LLM lock.
speakVision(text)  // LLM camera description. Sets 8s lock on speak().
```

Logs are prefixed:
- `TTS: ...` — regular navigation alert
- `TTS URGENT: ...` — urgent alert
- `Vision: ...` — LLM camera description
- `[LLM] Sending to Groq / model` — API request fired
- `[LLM] OK: ...` — API response received

---

### `mobile/android/src/jni_bridge.cpp` — C++/Java Bridge

Sets ALL Android-specific tuning (YAML config is not used on Android):

```cpp
cfg.frame_width  = 640;      // must be 640x640, NOT default 320x240
cfg.frame_height = 640;
cfg.depth_scale  = 3.5f;     // tuned for indoor mobile (was 2.0)
cfg.info_threshold = 7.0f;   // announce objects up to 7m away
cfg.confidence_threshold = 0.45f;
cfg.whitelist = { "person", "chair", ..., "wall" }; // "wall" is synthetic
```

Pipeline thread is pinned to high-performance CPU cores 4-7:
```cpp
cpu_set_t cpuset;
CPU_ZERO(&cpuset);
for (int c = 4; c <= 7; c++) CPU_SET(c, &cpuset);
sched_setaffinity(0, sizeof(cpuset), &cpuset);
```

---

## Part 3 — Critical Bugs Fixed (Port Phase)

### Bug 1: JNI Zombie Thread

**Symptom:** Background pipeline never stops when app goes background. Battery drain, memory leaks.

**Root cause:**
```cpp
// WRONG — local Pipeline copy inside thread
g_pipeline_thread = std::thread([cfg]() {
    Pipeline p(cfg);  // local!
    p.run();
});
// stop() called g_pipeline->stop() which is a DIFFERENT instance — thread never stops
```

**Fix:**
```cpp
// CORRECT — thread uses global instance
g_running.store(true);
g_pipeline_thread = std::thread([]() {
    if (!g_pipeline->init()) return;
    g_pipeline->run();
});

// stop():
g_pipeline->stop();
if (g_pipeline_thread.joinable()) g_pipeline_thread.join();
```
Also: `bool running_` → `std::atomic<bool> running_` to prevent data race.

---

### Bug 2: TTS Never Called on Android

**Symptom:** App runs, detects objects visually, phone is completely silent.

**Root cause:** `process_frame()` printed alerts to `std::cout`. Nobody reads stdout on Android. `speak_callback` existed in JNI but was never connected to `Pipeline`.

**Fix:** Add callback to Pipeline:
```cpp
// pipeline.hpp
using AlertCallback = std::function<void(const std::string&, bool)>;
void set_alert_callback(AlertCallback cb);

// pipeline.cpp — in process_frame():
if (alert_callback_) alert_callback_(message, is_urgent);

// jni_bridge.cpp — after creating pipeline:
g_pipeline->set_alert_callback(speak_callback);
```

---

### Bug 3: Memory Leaks in DecisionEngine

**Symptom:** Gradual memory growth over hours.

**Root cause:** `create_alert()` returned raw `Alert*` from `new`. Any exception in caller = permanent leak.

**Fix:** `std::optional<Alert>` — stack allocated, zero new/delete:
```cpp
std::optional<Alert> create_alert(const TrackedObject& obj, size_t count);
// caller:
auto alert = create_alert(obj, count);
if (alert.has_value()) candidates.push_back(alert.value());
```

---

### Bug 4: Dangling ONNX Name Pointers

**Symptom:** Random crashes during inference, especially under memory pressure.

**Root cause:**
```cpp
// WRONG — temporary destroyed immediately, pointer dangles
const char* name = session_.GetInputNameAllocated(0, allocator).get();
```

**Fix:** Store owning pointer as class member:
```cpp
// .hpp:
std::vector<Ort::AllocatedStringPtr> input_names_ptrs_;
std::vector<const char*> input_names_;

// .cpp:
input_names_ptrs_.push_back(session_.GetInputNameAllocated(i, allocator));
input_names_.push_back(input_names_ptrs_.back().get()); // valid because owner lives
```

---

### Bug 5: YOLOv8 Output Tensor Transposed → Garbage Detections

**Symptom:** Random bounding boxes scattered everywhere, or no detections at all.

**Root cause:** YOLOv8 ONNX output shape: `[1, 84, 8400]` (features × detections).
Code read `output_shape[1]=84` as num_detections, `output_shape[2]=8400` as num_features → completely wrong.

**Fix:**
```cpp
bool transposed = (dim1 < dim2); // [84, 8400] has dim1 < dim2
if (transposed) {
    for (int d = 0; d < num_dets; d++)
        for (int f = 0; f < num_features; f++)
            out[d * num_features + f] = raw[f * num_dets + d];
}
```

---

### Bug 6: MiDaS Tensor Dimension Crash (Core Dump on First Detection)

**Symptom:** App runs fine with empty scene, crashes the exact moment any object appears.

**Root cause:** Code assumed 4D output `[B, C, H, W]`. Some ONNX exports return 3D `[B, H, W]`. `output_shape[3]` on 3-element vector → out-of-bounds crash.

**Fix:**
```cpp
auto shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
int out_h = 256, out_w = 256;
if (shape.size() >= 4) {
    out_h = (int)shape[2]; out_w = (int)shape[3];
} else if (shape.size() == 3) {
    out_h = (int)shape[1]; out_w = (int)shape[2];
}
```

---

### Bug 7: ONNX Thread Pool Thrashing (22 FPS → 5 FPS)

**Symptom:** Adding more CPU threads makes FPS worse.

**Root cause:** YOLOv8n operates on small 640×640 tensors. 28 threads spend more time on synchronization locks than actual matrix math. L3 cache thrashing.

**Fix:** `num_threads = 4` (proven sweet spot for small inference models):
```cpp
Ort::SessionOptions opts;
opts.SetIntraOpNumThreads(4);
```

---

## Part 4 — Android-Specific Bugs

### Android Bug 1: Sideways Bounding Boxes (Sensor Rotation)

**Symptom:** Boxes are rotated 90°, floating in wrong screen positions.

**Root cause:** Camera sensor is landscape. CameraX delivers landscape frames with a rotation hint. C++ cropped the raw landscape frame → YOLO processed a sideways image.

**Fix:** Rotate the `cv::Mat` before cropping:
```cpp
// jni_bridge.cpp — push_frame() receives rotation degrees from CameraX
if (rotation != 0) {
    switch (rotation) {
        case 90:  cv::rotate(bgr, bgr, cv::ROTATE_90_CLOCKWISE); break;
        case 270: cv::rotate(bgr, bgr, cv::ROTATE_90_COUNTERCLOCKWISE); break;
        case 180: cv::rotate(bgr, bgr, cv::ROTATE_180); break;
    }
}
bgr = center_crop_square(bgr); // AFTER rotation
```

---

### Android Bug 2: 9:16 vs 1:1 Coordinate Mismatch

**Symptom:** Even after rotation fix, boxes float in wrong positions.

**Root cause:** AI pipeline is 640×640 square. `PreviewView` with `FILL_CENTER` displays 9:16. Mapping square→9:16 coordinates required complex math that fought Android's scaling.

**Fix:** Force PreviewView to a 1:1 square in layout XML:
```xml
<androidx.camera.view.PreviewView
    android:id="@+id/preview_view"
    app:layout_constraintDimensionRatio="H,1:1"
    app:layout_constraintTop_toTopOf="parent"
    app:layout_constraintStart_toStartOf="parent"
    app:layout_constraintEnd_toEndOf="parent" />
```
`OverlayView` anchored to same square → coordinate mapping = simple linear scale.

---

### Android Bug 3: 320×240 "Squash" Distortion

**Symptom:** Boxes tiny and vertically squished despite same model as desktop.

**Root cause:** After cropping to 720×720, pipeline fell back to `types.hpp` default `frame_width=320, frame_height=240`. 720×720 squashed to 320×240 rectangle, then YOLO stretched it to 640×640 — distorting real-world shapes.

**Fix:** In `jni_bridge.cpp`, always override:
```cpp
cfg.frame_width  = 640;
cfg.frame_height = 640;
```

---

### Android Bug 4: "Horse in the Office" — Missing Whitelist

**Symptom:** App detects horses, airplanes, cows in an office building.

**Root cause:** Android JNI bypassed YAML config. Empty `whitelist` = all 80 COCO classes enabled. Office chairs → horses.

**Fix:** Hardcode indoor whitelist in `jni_bridge.cpp`:
```cpp
cfg.whitelist = {
    "person", "bicycle", "car", "motorcycle", "bus", "truck",
    "chair", "couch", "bed", "dining table", "toilet", "tv", "laptop",
    "cell phone", "bottle", "cup", "backpack", "handbag", "suitcase",
    "umbrella", "book", "potted plant", "dog", "cat",
    "stop sign", "fire hydrant", "bench",
    "refrigerator", "microwave", "oven", "sink", "clock", "vase", "scissors",
    "wall"  // synthetic label — injected by depth check, not YOLO
};
```

---

### Android Bug 5: NNAPI Re-entrancy Crash

**Symptom:** Crash with `CHECK` failure from `libneuraletworks` during camera operations.

**Root cause:** NNAPI is not re-entrant. Two overlapping inference calls = internal assert.

**Fix:** Drop frames if inference is busy:
```cpp
void Pipeline::push_frame(const uint8_t* data, int w, int h, int rot) {
    if (!running_.load()) return;
    if (!frame_mutex_.try_lock()) return; // skip frame if busy — never block
    std::lock_guard<std::mutex> hold(frame_mutex_, std::adopt_lock);
    // ... inference ...
}
```

---

### Android Bug 6: RHVoice Blocked by Android Package Visibility

**Symptom:** `TextToSpeech` initialized with RHVoice engine package name but silently falls back to Google TTS. RHVoice never used even when installed and configured.

**Root cause found in `adb logcat`:**
```
AppsFilter: interaction: com.navigation.assistant
  → com.github.olga_yakovleva.rhvoice.android BLOCKED
```
Android 11+ enforces package visibility. Apps can't see other apps unless declared in manifest.

**Fix — add `<queries>` to `AndroidManifest.xml`:**
```xml
<manifest ...>
    ...
    <queries>
        <intent>
            <action android:name="android.intent.action.TTS_SERVICE" />
        </intent>
        <package android:name="com.github.olga_yakovleva.rhvoice.android" />
    </queries>

    <application ...>
```
This was invisible in all logs except raw `adb logcat` grep for "RHVoice".

---

## Part 5 — Runtime Issues Found on Real Device

These bugs only appear during live testing. No simulation or local build catches them.

---

### Issue 1: Confusing Log Labels — TTS and LLM Both Named "Voice"

**Symptom:** Log shows:
```
[23:38:40] Voice: Path is clear ahead.
[23:38:55] Voice: A bed with patterned linens is on the right...
[23:38:56] Voice: Path is clear ahead.
```
Impossible to tell which line came from the C++ navigation engine and which from the LLM API.

**Fix:**
```java
public void speak(String text) {       // C++ navigation alerts
    appendLog(normalLogs, "TTS: " + text);
}
public void speakUrgent(String text) { // urgent navigation alerts
    appendLog(normalLogs, "TTS URGENT: " + text);
}
public void speakVision(String text) { // LLM camera descriptions
    appendLog(normalLogs, "Vision: " + text);
}
```

---

### Issue 2: LLM Description Never Spoken (90% of the Time)

**Symptom:** Dev logs show `[LLM] OK: A person is sitting...` (API returned successfully) but TTS never says it. Only speaks maybe 1 in 10 times.

**Root cause:** Both navigation TTS and LLM used `QUEUE_FLUSH`. Timeline:
```
t=0s:  LLM API request sent
t=2s:  LLM response arrives → speak(description) called → QUEUE_FLUSH → starts speaking
t=3s:  C++ pipeline fires "Path is clear ahead" → speak() → QUEUE_FLUSH → KILLS LLM speech
```
The pipeline fires every ~3-7s. LLM response takes ~2-3s. The pipeline alert almost always arrives while the LLM description is mid-speech.

**Fix — 8-second vision lock:**
```java
private long lastVisionSpeakMs = 0;
private static final long VISION_LOCK_MS = 8000;

public void speak(String text) {
    // Skip regular nav alerts while LLM description is playing
    if (System.currentTimeMillis() - lastVisionSpeakMs < VISION_LOCK_MS) return;
    if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
    appendLog(normalLogs, "TTS: " + text);
}

public void speakUrgent(String text) {
    lastVisionSpeakMs = 0;  // urgent always breaks through, resets lock
    if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
    appendLog(normalLogs, "TTS URGENT: " + text);
}

public void speakVision(String text) {
    lastVisionSpeakMs = System.currentTimeMillis(); // start the lock
    if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
    appendLog(normalLogs, "Vision: " + text);
}

// In requestSceneDescription — use speakVision, NOT speak:
runOnUiThread(() -> speakVision(finalDesc));
```

---

### Issue 3: Wall Not Detected (Two Separate Bugs Stacked)

**Symptom:** Walking directly into a blank white wall — nothing announced. The wall has no texture, YOLO cannot detect it (not a COCO class).

#### Sub-bug A: Threshold Scale Completely Wrong

The depth check in `pipeline.cpp` had:
```cpp
double high_thresh = 0.70 * 255.0; // = 178.5
if (mean_depth > high_thresh) { ... }
```
But `depth_map` is `CV_32F` normalized to `0.0–1.0`. A value of `178.5` on a 0-1 float is **impossible to exceed**. The entire wall detection block was dead code from day one.

**Correct threshold:**
```cpp
double high_thresh = 0.65; // 0.0–1.0 float, ~1m obstacle
```

#### Sub-bug B: Depth Not Run When YOLO Finds Nothing

The original code:
```cpp
if (!detections_.empty()) {
    cv::Mat depth_map = depth_estimator_->estimate(frame);
    // ... assign distances to detections
}
// else: no detections → depth skipped entirely
```
A blank wall produces zero YOLO detections → depth is never computed → wall check never runs.

**Fix — always run depth, check center zone:**
```cpp
// Always run depth estimation
cv::Mat depth_map = depth_estimator_->estimate(frame);

if (!detections_.empty()) {
    for (auto& det : detections_) {
        det.direction = get_direction(det.center_x, fw, ...);
        det.distance_m = depth_estimator_->get_distance(depth_map, det.bbox);
    }
}

// Depth-only wall check — runs regardless of YOLO output
if (!depth_map.empty()) {
    int cx = depth_map.cols / 2, cy = depth_map.rows / 2;
    int rw = depth_map.cols / 6, rh = depth_map.rows / 6; // center 30%
    cv::Rect roi(cx - rw, cy - rh, rw * 2, rh * 2);
    roi &= cv::Rect(0, 0, depth_map.cols, depth_map.rows);
    double mean_depth = cv::mean(depth_map(roi))[0];

    if (mean_depth > 0.65) { // float 0-1, NOT 0.70*255
        Detection wall_det;
        wall_det.label = "wall";       // must be in whitelist!
        wall_det.confidence = 1.0f;
        wall_det.direction = "CENTER";
        wall_det.distance_m = 1.0f;   // ~1m heuristic
        wall_det.center_x = fw / 2.0f;
        wall_det.center_y = config_.frame_height / 2.0f;
        wall_det.bbox = {cx - rw, cy - rh, cx + rw, cy + rh};
        wall_det.class_id = 999;      // synthetic, not a COCO class
        detections_.push_back(wall_det);
    }
}
```
Also add `"wall"` to the whitelist in `jni_bridge.cpp`.

**Tuning the threshold:**
- If wall triggers in open rooms (false positives) → raise to `0.75`
- If wall not triggering until very close → lower to `0.55`
- The tracker still requires `consecutive_frames_required = 3` — so wall must persist 3 frames before announcing

---

### Issue 4: TTS Speaks Stale Information (5-Second Lag)

**Symptom:** Bounding box for detected object appears immediately (1s). TTS speaks the alert 5 seconds later. By then the scene has completely changed. Example: laptop is visibly boxed in green on screen, but TTS says "Path is clear ahead" — because that was true 5 seconds ago.

**Root cause:** `speak()` used `QUEUE_ADD`. At 1 FPS, pipeline generates one alert per second. Over 3-5 seconds, alerts pile up in the TTS queue. The user hears a 5-second backlog of outdated information.

**Fix:** `QUEUE_FLUSH` — new alert immediately cancels whatever is playing:
```java
public void speak(String text) {
    if (System.currentTimeMillis() - lastVisionSpeakMs < VISION_LOCK_MS) return;
    // FLUSH: cancels stale queued speech, speaks this alert immediately
    if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
    appendLog(normalLogs, "TTS: " + text);
}
```
**Tradeoff:** If two alerts fire in the same frame, only the last one is heard. The pipeline sorts alerts by priority and limits to `max_alerts = 2`, so the most urgent always fires last = wins.

---

### Issue 5: LLM API Prompt Too Verbose

**Symptom:** LLM returns a 3-paragraph description: "The room is dimly lit. A person wearing headphones and a black shirt is sitting on a bed, focused on a laptop computer in their lap. The room has clothes hanging in the background, and a white plastic chair is partially visible in the foreground. Brightly colored bedding..."

For a blind user navigating, this is overwhelming and too slow.

**Fix — constrain the prompt:**
```java
String prompt = "Describe this scene very briefly in 1 short sentence for a blind person. " +
                "Just list the most important objects and their general location. No extra details.";
```

---

### Issue 6: LLM Always Responds in English Regardless of App Language

**Symptom:** User toggles app to Hindi. Navigation TTS alerts correctly speak in Hindi ("Aage rasta saaf hai"). But LLM camera description always returns in English ("A bed with...").

**Root cause:** The API prompt was always `"Describe this scene..."` regardless of language setting.

**Fix — read app language preference:**
```java
String lang = getSharedPreferences("app_prefs", MODE_PRIVATE).getString("language", "en");
String prompt;
if ("hi".equals(lang)) {
    prompt = "Describe this scene very briefly in 1 short sentence in Hindi for a blind person. " +
             "Just list the most important objects. No extra details.";
} else {
    prompt = "Describe this scene very briefly in 1 short sentence for a blind person. " +
             "Just list the most important objects and their general location. No extra details.";
}
```

---

### Issue 7: Qwen Reasoning Model Thinks for 30 Seconds Before Answering

**Symptom:** After tapping Vision/LLM button, TTS speaks nothing for 30+ seconds, then reads out "The scene shows... Wait, let me think... First I should consider the depth... Given that the objects are..." before finally saying the actual description.

**Root cause:** `qwen/qwen3.6-27b` is a reasoning model. It generates a `<think>...</think>` chain-of-thought block before the actual answer. These tokens:
1. Add 10-30 seconds of generation time (all billed/delayed)
2. Get returned in the API response and TTS reads the entire internal monologue aloud

**Fix — three layers of defense:**

**Layer 1 — Disable reasoning at API level (Groq-specific):**
```java
// Tells Groq to skip the reasoning phase entirely — fastest
if (providerIndex == 0) {
    payload.put("reasoning_effort", "none");
}
```

**Layer 2 — Strip `<think>` blocks from response:**
```java
// Safety net in case the server still returns thinking tokens
description = description.replaceAll("(?s)<think>.*?</think>\\s*", "");
```

**Layer 3 — Prompt instruction:**
```
"Direct answer only, do not think or show chain of thought."
```

---

### Issue 8: Wrong Groq Model — Text-Only Models Don't Accept Images

**Symptom:** API returns `400 Bad Request` or model deprecation error. LLM never works.

**Timeline of failures:**
1. Default model `llama3-8b-8192` → text-only → `400 Bad Request` (cannot process images)
2. Changed to `llama-3.2-11b-vision-preview` → `400: The model has been decommissioned`
3. Changed to `qwen/qwen3.6-27b` but typed `qwen3.6-27b` (missing vendor prefix) → `404: model does not exist`

**How to find valid models for your key:**
```bash
curl https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer YOUR_GROQ_KEY" | jq -r '.data[].id'
```

**Active vision model as of July 2026:** `qwen/qwen3.6-27b`
(Always include the full ID with vendor prefix: `qwen/` not just `qwen3.6-27b`)

**Lessons:**
- Only vision models work — we send base64 camera frames in every request
- Groq rotates/deprecates models frequently — check the list on each update
- The `reasoning_effort: none` parameter only works on Groq (do not send it to OpenAI or custom providers)

---

### Issue 9: What Does "Mode: skip" Mean in Dev Logs?

**Not a bug.** This line:
```
FPS: 1.1 | Mode: skip
```
Appears because `process_every_n_frames = 3`. "Skip" means this camera frame was intentionally NOT run through YOLO/MiDaS — the pipeline showed the bounding boxes from the previous inference run (cached). This is why:
- Bounding boxes update every frame (fast, drawn from cache)
- TTS alerts fire less often (only when inference actually runs)

If you see `Mode: full` it means every single frame is being processed (expensive, no skipping).

---

## Part 6 — Performance Summary

| Model | Size | FPS (Snapdragon) | Notes |
|---|---|---|---|
| `yolov8n_int8.onnx` | 3.2 MB | ~1.4 FPS | Current default. Best speed. |
| `yolov8s_int8.onnx` | 10.8 MB | ~0.7 FPS | Better detection. User kept this version. |
| MiDaS small | 17 MB | runs with YOLO | Depth not absolute — relative only |

**Hard limits:**
- Running YOLO + MiDaS simultaneously on mobile CPU → ~1 FPS. This is a hardware limit.
- Chair detection is consistently poor (oblique angles, partial occlusion). No easy fix.
- Wall detection via depth is heuristic, not reliable on all surfaces.

---

## Part 7 — Config Reference (Android / `jni_bridge.cpp`)

| Parameter | Value | Effect |
|---|---|---|
| `depth_scale` | 3.5 | MiDaS raw → meters (higher = farther reported) |
| `info_threshold` | 7.0m | Objects farther than this: silent |
| `warning_threshold` | 5.0m | Objects within this: "nearby" alert |
| `urgent_threshold` | 2.0m | Objects within this: "very close / urgent" |
| `alert_cooldown_seconds` | 7.0s | Same object won't re-announce for 7s |
| `path_clear_interval_seconds` | 15.0s | "Path is clear" at most every 15s |
| `confidence_threshold` | 0.45 | Lower = more false positives |
| `consecutive_frames_required` | 3 | Object must persist 3 frames |
| `wall_depth_threshold` | 0.65 | CV_32F 0-1 range — do NOT multiply by 255 |
| `VISION_LOCK_MS` (Java) | 8000ms | Navigation TTS suppressed 8s after LLM |
| `process_every_n_frames` | 3 | "Mode: skip" in logs |

---

## Part 8 — Build & Debug Commands

```bash
# Build and install
cd mobile/android
./gradlew assembleDebug
adb install -r build/outputs/apk/debug/ai_navigation_assistant-v0.0.3-alpha.apk

# Watch all app logs live
adb logcat | grep NavAssistant

# Check LLM API errors
adb logcat -d | grep -i "LLM" | tail -20

# Check why RHVoice isn't working
adb logcat -d | grep -i "RHVoice" | tail -20

# List valid Groq models for your key
curl https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer YOUR_KEY" | jq -r '.data[].id'
```

---

## Part 9 — PC Desktop/Testing Fixes

### Desktop Bug 1: Video File "Stuck" and Pacing
**Symptom:** When passing a pre-recorded `.mp4` video via `--video`, it processes instantly in a fraction of a second and gets "stuck" on the final frame.
**Root cause:** `CameraStream` had a tight loop (`reader_loop`) that read frames continuously without sleeping, causing it to consume the entire video file before the pipeline could process it.
**Fix:** Read `cv::CAP_PROP_FPS` and added `std::this_thread::sleep_for(1000 / fps)` to pace the reader. Also added `cap_.set(cv::CAP_PROP_POS_FRAMES, 0)` so the video loops indefinitely when testing.

### Desktop Bug 2: Video Cropped and Horizontally Stretched
**Symptom:** In the C++ PC Dashboard, portrait videos appeared heavily zoomed in (sides cut off) and squished/stretched.
**Root cause:** The pipeline forced a `center_crop_square()` on the video, chopping off 40% of the horizontal view. Then the HUD was scaling the 640x640 frame uniformly back up to 900x900, totally destroying the 16:9 aspect ratio.
**Fix:** 
1. Removed `center_crop_square` on desktop. YOLO handles aspect ratio distortion acceptably well, so preserving the full FOV is preferred for PC testing.
2. Saved the `original_aspect_ = (float)width / height` of the raw video before YOLO squishes it.
3. In `pipeline.cpp` HUD generation, dynamically scale the display using `original_aspect_` (e.g. 1244x700 for a 16:9 video) to reconstruct the true aspect ratio in the UI.
