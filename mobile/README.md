# AI Navigation Assistant — Mobile C++ Port

Real-time object detection + depth estimation + navigation assistant in pure C++.

## Architecture

```
mobile/
├── CMakeLists.txt              # Build for desktop Linux
├── include/                    # Header files
│   ├── types.hpp               # Shared types (Detection, TrackedObject, Config)
│   ├── detector.hpp            # YOLOv8 ONNX Runtime wrapper
│   ├── depth_estimator.hpp     # MiDaS ONNX Runtime wrapper
│   ├── tracker.hpp             # ObjectTracker (greedy IoU matching)
│   ├── decision_engine.hpp     # Alert decision logic
│   ├── direction.hpp           # LEFT/CENTER/RIGHT zones
│   ├── frame_utils.hpp         # Annotation, status bar, base64
│   ├── camera.hpp              # Threaded camera capture
│   └── pipeline.hpp            # Main pipeline orchestrator
├── src/                        # Implementation files
│   ├── main.cpp                # Entry point + config loader
│   ├── pipeline.cpp            # Pipeline loop
│   ├── detector.cpp            # YOLOv8 ONNX inference
│   ├── depth_estimator.cpp     # MiDaS ONNX inference
│   ├── tracker.cpp             # Hungarian/greedy tracker
│   ├── decision_engine.cpp     # Alert generation
│   ├── direction.cpp           # Zone computation
│   ├── frame_utils.cpp         # Drawing utilities
│   └── camera.cpp              # Camera reader
├── models/                     # ONNX model files
│   ├── yolov8n.onnx            # YOLOv8 nano (fastest)
│   ├── yolov8s.onnx            # YOLOv8 small (balanced)
│   └── midas_v21_small_256.onnx # MiDaS depth (export target)
├── android/                    # Android-specific files
│   ├── AndroidManifest.xml
│   ├── build.gradle
│   ├── settings.gradle
│   ├── gradle.properties
│   ├── res/layout/activity_main.xml
│   └── src/...
│       ├── MainActivity.java        # JNI shell + TTS
│       └── jni_bridge.cpp           # JNI → C++ pipeline
├── scripts/
│   ├── download_deps.sh        # Download ONNX Runtime + check deps
│   └── export_midas_onnx.py    # Export MiDaS .pt → .onnx
└── third_party/                # Third-party libs (gitignored)
```

## Build for Desktop (Linux)

```bash
# 1. Install system deps
sudo pacman -S opencv yaml-cpp   # Arch/Garuda
# or: sudo apt install libopencv-dev libyaml-cpp-dev

# 2. Download ONNX Runtime
bash scripts/download_deps.sh

# 3. Export MiDaS to ONNX
python scripts/export_midas_onnx.py

# 4. Build
mkdir -p build && cd build
cmake .. -DONNXRUNTIME_ROOT=../third_party/onnxruntime
make -j$(nproc)

# 5. Run
./ai_navigation_assistant --config ../../config.yaml
```

## Build for Android

1. Install Android SDK + NDK (see `neo/issues/android-setup-guide.md`)
2. Export MiDaS ONNX model (step 3 above)
3. Build via Gradle or Android Studio:
   ```bash
   cd mobile/android
   ./gradlew assembleDebug
   ```
4. APK at `android/build/outputs/apk/debug/`

## Key Differences from Python Version

| Component | Python (original) | C++ (mobile port) |
|---|---|---|
| YOLO inference | PyTorch + ultralytics | ONNX Runtime C++ |
| MiDaS inference | PyTorch + torch.hub | ONNX Runtime C++ |
| Tracker | Hungarian (scipy) | Greedy matching (no scipy dep) |
| TTS | pyttsx3 / gTTS | Android TTS (JNI) |
| Config | yaml (PyYAML) | yaml-cpp |
| Frame annotation | OpenCV Python | OpenCV C++ |
| Camera | OpenCV threaded | OpenCV threaded |

## Targets

- **arm64-v8a** (Android phones, Raspberry Pi 4/5)
- **x86_64** (Desktop Linux testing)
