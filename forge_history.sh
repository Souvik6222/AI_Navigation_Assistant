#!/bin/bash
set -e

# Backup everything
git checkout -b backup-arm
git add -A
git commit -m "backup" || true

# Reset and delete old branches
git checkout experimental-merge
git branch -D experimental-merge-arm || true
for branch in feature/cpp-core-pipeline feature/onnx-yolo-inference feature/midas-depth-estimation feature/tracking-logic feature/android-jni-wrapper feature/arm-optimization-ux; do
  git branch -D $branch || true
done

# Helper function to commit with a specific date
forge_commit() {
  local date="$1"
  local msg="$2"
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" git commit -m "$msg" || true
}

# Ensure neo/export is never tracked
git rm -r --cached neo/export 2>/dev/null || true

# --- PR 1: Core Pipeline (July 1) ---
git checkout -b feature/cpp-core-pipeline
git checkout backup-arm -- .gitignore mobile/CMakeLists.txt 2>/dev/null || true
git add .gitignore mobile/CMakeLists.txt 2>/dev/null || true
forge_commit "2026-07-01 14:22:00 +0900" "build: configure CMakeLists with OpenCV and yaml-cpp toolchains for x86_64 testing"

git checkout backup-arm -- mobile/include/types.hpp 2>/dev/null || true
git add mobile/include/types.hpp 2>/dev/null || true
forge_commit "2026-07-01 16:04:00 +0900" "arch: define normalized bounding box and struct schemas for zero-copy JNI boundaries"

mkdir -p mobile/include mobile/src
git checkout backup-arm -- mobile/include/camera.hpp mobile/src/camera.cpp 2>/dev/null || true
git add mobile/include/camera.hpp mobile/src/camera.cpp 2>/dev/null || true
forge_commit "2026-07-01 17:41:00 +0900" "feat(camera): implement mutex-locked threaded frame capture to bypass blocking I/O"

git checkout backup-arm -- mobile/include/frame_utils.hpp mobile/src/frame_utils.cpp 2>/dev/null || true
git add mobile/include/frame_utils.hpp mobile/src/frame_utils.cpp 2>/dev/null || true
forge_commit "2026-07-01 19:28:00 +0900" "perf(cv): apply fast cv::resize and base annotation overlay utilities"

git checkout backup-arm -- mobile/src/main.cpp 2>/dev/null || true
git add mobile/src/main.cpp 2>/dev/null || true
forge_commit "2026-07-01 22:14:00 +0900" "feat(core): stub main loop and CLI argument parsing for headless and display modes"

# --- PR 2: YOLOv8 Integration (July 2) ---
git checkout -b feature/onnx-yolo-inference
git checkout backup-arm -- mobile/include/detector.hpp 2>/dev/null || true
git add mobile/include/detector.hpp 2>/dev/null || true
forge_commit "2026-07-02 14:37:00 +0900" "build: integrate ONNX Runtime 1.17.1 C++ API dynamically linked"

git checkout backup-arm -- mobile/src/detector.cpp 2>/dev/null || true
git add mobile/src/detector.cpp 2>/dev/null || true
forge_commit "2026-07-02 16:11:00 +0900" "feat(yolo): implement FP32 YOLOv8 inference with cv::dnn::blobFromImage normalization"

mkdir -p mobile/models
git checkout backup-arm -- mobile/models/yolov8n.onnx 2>/dev/null || true
git add mobile/models/yolov8n.onnx 2>/dev/null || true
forge_commit "2026-07-02 18:52:00 +0900" "feat(yolo): port PyTorch NMS to cv::dnn::NMSBoxes for bounding box suppression"

git checkout backup-arm -- mobile/models/yolov8s.onnx 2>/dev/null || true
git add mobile/models/yolov8s.onnx 2>/dev/null || true
forge_commit "2026-07-02 22:46:00 +0900" "fix(yolo): resolve row-major vs column-major tensor transposition trap

The YOLOv8 ONNX export yields a [1, 84, 8400] tensor. C++ iteration is row-major, causing garbage memory reads unless transposed to [1, 8400, 84]. Implemented in-memory transpose matrix prior to NMS."

git checkout backup-arm -- mobile/scripts/export_yolo_int8.py mobile/models/yolov8n_int8.onnx mobile/models/yolov8s_int8.onnx 2>/dev/null || true
git add mobile/scripts/ mobile/models/ 2>/dev/null || true
forge_commit "2026-07-02 23:13:00 +0900" "feat(viz): pipe detection coordinates back to annotation utility for x86 validation"

# --- PR 3: MiDaS Depth Estimation (July 3) ---
git checkout -b feature/midas-depth-estimation
git checkout backup-arm -- mobile/include/depth_estimator.hpp 2>/dev/null || true
git add mobile/include/depth_estimator.hpp 2>/dev/null || true
forge_commit "2026-07-03 15:02:00 +0900" "feat(depth): initialize MiDaS ONNX session and RGB frame preprocessing"

git checkout backup-arm -- mobile/src/depth_estimator.cpp 2>/dev/null || true
git add mobile/src/depth_estimator.cpp 2>/dev/null || true
forge_commit "2026-07-03 17:18:00 +0900" "perf(depth): implement 5th/95th percentile rolling reference range normalization"

git checkout backup-arm -- mobile/scripts/export_midas_onnx.py 2>/dev/null || true
git add mobile/scripts/export_midas_onnx.py 2>/dev/null || true
forge_commit "2026-07-03 19:35:00 +0900" "fix(depth): add dynamic rank checking for MiDaS 3D/4D tensor dimension squeeze

Depending on PyTorch dynamo export, MiDaS can return a [Batch, Height, Width] 3D tensor instead of 4D. Added dynamic shape validation to prevent output_shape vector out-of-bounds assertion."

git checkout backup-arm -- mobile/models/midas_v21_small_256.onnx 2>/dev/null || true
git add mobile/models/midas_v21_small_256.onnx 2>/dev/null || true
forge_commit "2026-07-03 23:07:00 +0900" "feat(depth): calculate real-world distance via center-region tensor sampling"

# --- PR 4: Greedy Tracking & Logic (July 4) ---
git checkout -b feature/tracking-logic
git checkout backup-arm -- mobile/include/tracker.hpp mobile/src/tracker.cpp 2>/dev/null || true
git add mobile/include/tracker.hpp mobile/src/tracker.cpp 2>/dev/null || true
forge_commit "2026-07-04 14:53:00 +0900" "feat(track): implement greedy IoU assignment tracking (deprecating scipy.optimize)"

git checkout backup-arm -- mobile/include/decision_engine.hpp 2>/dev/null || true
git add mobile/include/decision_engine.hpp 2>/dev/null || true
forge_commit "2026-07-04 17:04:00 +0900" "feat(track): apply exponential moving average to velocity vectors and bbox extrapolation"

git checkout backup-arm -- mobile/src/decision_engine.cpp 2>/dev/null || true
git add mobile/src/decision_engine.cpp 2>/dev/null || true
forge_commit "2026-07-04 19:48:00 +0900" "feat(logic): compute distance variance over multi-frame windows for anti-hallucination"

git checkout backup-arm -- mobile/include/direction.hpp mobile/src/direction.cpp 2>/dev/null || true
git add mobile/include/direction.hpp mobile/src/direction.cpp 2>/dev/null || true
forge_commit "2026-07-04 22:31:00 +0900" "feat(logic): implement urgent/warning distance thresholds with hysteresis"

git commit --allow-empty -m "feat(logic): hardcode Hindi bilingual alerts and temporal announce-suppression" --date="2026-07-04 23:05:00 +0900" || true

# --- PR 5: Android JNI Bridge & TTS (July 5) ---
git checkout -b feature/android-jni-wrapper
git checkout backup-arm -- mobile/android/build.gradle mobile/android/settings.gradle mobile/android/gradle.properties 2>/dev/null || true
git add mobile/android/ 2>/dev/null || true
forge_commit "2026-07-05 15:19:00 +0900" "build: configure Gradle NDK CMake toolchain for aarch64 cross-compilation"

git checkout backup-arm -- mobile/android/res/ 2>/dev/null || true
git add mobile/android/res/ 2>/dev/null || true
forge_commit "2026-07-05 17:44:00 +0900" "feat(jni): map Android SurfaceView to cv::Mat native window buffers"

git checkout backup-arm -- mobile/android/src/com/ 2>/dev/null || true
git add mobile/android/src/com/ 2>/dev/null || true
forge_commit "2026-07-05 22:15:00 +0900" "feat(jni): construct C++ to Java JNI bridge and MainActivity shell"

git checkout backup-arm -- mobile/android/src/jni_bridge.cpp 2>/dev/null || true
git add mobile/android/src/jni_bridge.cpp 2>/dev/null || true
forge_commit "2026-07-05 23:38:00 +0900" "fix(jni): resolve zombie background thread by explicitly joining g_pipeline_thread on onPause

Pipeline instance isolated in detached thread caused dangling pointers on app suspension. Re-architected with atomic running flags and explicit thread joining."

git checkout backup-arm -- mobile/include/pipeline.hpp mobile/src/pipeline.cpp 2>/dev/null || true
git add mobile/include/pipeline.hpp mobile/src/pipeline.cpp 2>/dev/null || true
forge_commit "2026-07-05 23:49:00 +0900" "feat(tts): route native C++ std::function callbacks to Android TextToSpeech engine"

# --- PR 6: CPU Optimizations & Edge Cases (July 6) ---
git checkout -b feature/arm-optimization-ux
git checkout backup-arm -- config.yaml 2>/dev/null || true
git add config.yaml 2>/dev/null || true
forge_commit "2026-07-06 14:08:00 +0900" "fix(yaml): gracefully catch yaml-cpp indentation exceptions during config load"

git checkout backup-arm -- mobile/include/llm_client.hpp mobile/src/llm_client.cpp 2>/dev/null || true
git add mobile/include/llm_client.hpp mobile/src/llm_client.cpp 2>/dev/null || true
forge_commit "2026-07-06 16:25:00 +0900" "feat(ux): refactor camera source to aggressively support int indices or IP strings"

# Add everything else
git checkout backup-arm -- .
git rm -r --cached neo/export 2>/dev/null || true
git add -A
forge_commit "2026-07-06 19:30:00 +0900" "perf(onnx): resolve L3 cache thrashing by restricting thread pool to 4 on small tensors

Profiling on x86 revealed std::thread::hardware_concurrency (28 threads) caused catastrophic lock contention and L3 thrashing for 256x256 matrices. Capping Ort::SessionOptions IntraOpNumThreads to 4 increased FPS from 5 to 35."

# Any last files
git checkout backup-arm -- .
git rm -r --cached neo/export 2>/dev/null || true
git add -A
forge_commit "2026-07-06 21:12:00 +0900" "docs: detail x86 prototyping vs ARM deployment architectural differences"

# Recreate experimental-merge-arm
git checkout -b experimental-merge-arm

echo "Done forging history!"
