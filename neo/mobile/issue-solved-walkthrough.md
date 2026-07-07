# Mobile C++ Port — Walkthrough of Changes

## Summary

Fixed 5 critical bugs, added 1 high-priority feature, and implemented 2 bonus enhancements across **12 files** (8 modified, 1 new).

---

## Critical Fix 1: JNI Zombie Thread

**Files:** [pipeline.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/pipeline.hpp), [pipeline.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/pipeline.cpp), [jni_bridge.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/src/jni_bridge.cpp)

**Problem:** The JNI `start()` created a local `Pipeline` copy inside the thread. The `stop()` function called `g_pipeline->stop()` on a *different* global instance that was never run, so the background thread was never signaled to stop (zombie thread). Also, `running_` was a plain `bool` — a data race when read/written across threads.

**Fix:**
- Changed `bool running_` → `std::atomic<bool> running_` 
- Added `Pipeline::stop()` that sets `running_.store(false)`
- JNI `start()` now uses the global `g_pipeline` directly in the thread
- JNI `stop()` calls `g_pipeline->stop()` then `g_pipeline_thread.join()` for clean shutdown

---

## Critical Fix 2: Missing TTS Connection

**Files:** [pipeline.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/pipeline.hpp), [pipeline.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/pipeline.cpp), [jni_bridge.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/src/jni_bridge.cpp)

**Problem:** Alerts were only printed to `stdout`. On Android, nobody reads stdout — the JNI `speak_callback` was never called. Users would never hear any TTS alerts.

**Fix:**
- Added `std::function<void(const std::string&, bool)> alert_callback_` to Pipeline
- Added `set_alert_callback()` method
- `process_frame()` now invokes the callback for each alert (respects current language setting)
- JNI bridge wires `speak_callback` → `g_pipeline->set_alert_callback(speak_callback)` after construction
- JNI `speak_callback` now properly handles `GetEnv`/`AttachCurrentThread` with exception clearing

---

## Critical Fix 3: Memory Leaks in DecisionEngine

**Files:** [decision_engine.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/decision_engine.hpp), [decision_engine.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/decision_engine.cpp)

**Problem:** `create_alert()` and `check_path_clear()` returned raw `Alert*` pointers via `new`. Manual `delete` was required in `evaluate()`. Any missed delete = memory leak. On a mobile device running 24/7, this compounds.

**Fix:**
- Changed return types from `Alert*` → `std::optional<Alert>`
- All `Alert` objects are now stack-allocated
- `evaluate()` uses `std::vector<Alert>` instead of `std::vector<Alert*>`
- Zero `new`/`delete` calls remain

---

## Critical Fix 4: Dangling ONNX Name Pointers

**Files:** [detector.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/detector.hpp), [detector.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/detector.cpp), [depth_estimator.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/depth_estimator.hpp), [depth_estimator.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/depth_estimator.cpp)

**Problem:** `GetInputNameAllocated()` returns an `Ort::AllocatedStringPtr` (unique_ptr). The code called `.get()` on the temporary and stored the raw `const char*`. The temporary was immediately destroyed → dangling pointer → UB / random crashes.

**Fix:**
- Added `std::vector<Ort::AllocatedStringPtr> input_names_ptrs_` and `output_names_ptrs_` as class members
- Store the owning pointers first, then extract `.get()` for the raw pointer vectors

---

## Critical Fix 5: YOLOv8 Output Transpose

**File:** [detector.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/detector.cpp)

**Problem:** YOLOv8 ONNX outputs shape `[1, 84, 8400]` (features × detections), but the code read `output_shape[1]` as `num_dets` and `output_shape[2]` as `num_features`. This gave `num_dets=84, num_features=8400` — completely wrong, producing garbage detections.

**Fix:**
- Detects transposed format by checking `dim1 < dim2`
- Transposes the output buffer from `[features, detections]` to `[detections, features]` before parsing

---

## High: Language Toggle for Android

**Files:** [pipeline.hpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/include/pipeline.hpp), [pipeline.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/pipeline.cpp), [jni_bridge.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/src/jni_bridge.cpp), [MainActivity.java](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/src/com/navigation/assistant/MainActivity.java), [activity_main.xml](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/res/layout/activity_main.xml)

- Added `Pipeline::toggle_language()` method
- Added `toggleLanguage()` JNI native method
- Added a "Lang: EN" button in the Android layout (top-right corner)
- Button switches between English and Hindi, also changes Android TTS locale

---

## Bonus #1: NNAPI Hardware Acceleration

**Files:** [detector.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/detector.cpp), [depth_estimator.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/depth_estimator.cpp)

- Added `#ifdef __ANDROID__` blocks that append NNAPI execution provider to ONNX Runtime session options
- Falls back gracefully to CPU if NNAPI is unavailable
- Also bumped `SetIntraOpNumThreads` from 1 → 2 for better multi-core utilization

---

## Bonus #2: INT8 Quantization Export

**File:** [export_yolo_int8.py](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/scripts/export_yolo_int8.py) (NEW)

Uses ONNX-native weight quantization (per-tensor symmetric INT8 with DequantizeLinear ops). No calibration data needed — works fully offline.

### Results

| Model | FP32 ONNX | INT8 ONNX | Reduction |
|---|---|---|---|
| **yolov8n** | 12.2 MB | 3.2 MB | **73%** |
| **yolov8s** | 42.8 MB | 10.8 MB | **75%** |

INT8 models are saved at:
- `mobile/models/yolov8n_int8.onnx`
- `mobile/models/yolov8s_int8.onnx`

---

## Verification

- ✅ All C++ changes reviewed for structural correctness
- ✅ INT8 quantization script ran successfully for both models
- ✅ INT8 models produced with significant size reduction (~4x)
- ⚠️ Cannot compile C++ without ONNX Runtime SDK installed on this machine (SDK is a build-time dependency fetched by CMake)
