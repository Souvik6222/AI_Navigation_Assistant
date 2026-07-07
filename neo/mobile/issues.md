 observations:

### 🚨 Critical Bugs & Memory Leaks

1. **JNI Thread Detachment (Major Bug)**:
   In `mobile/android/src/jni_bridge.cpp`, the pipeline is launched in a background thread like this:
   ```cpp
   g_pipeline_thread = std::thread([cfg]() {
       Pipeline p(cfg); // <-- Local instance!
       if (p.init()) { p.run(); }
   });
   ```
   But the `stop()` method just sets `g_running.store(false)`. The local `Pipeline p` relies on its internal `p.running_` flag to stop. Because it's isolated, `stop()` will never actually kill the thread! Furthermore, `g_pipeline` (the global pointer) is allocated but never actually run. This will cause zombie threads and memory leaks on Android when the app goes to the background.

2. **Missing TTS Connection (Architecture Gap)**:
   The JNI bridge defines a `speak_callback` to trigger Android's native TTS. However, `Pipeline::process_frame` just prints alerts to `std::cout`. It never calls the JNI callback! 
   **Fix**: The `Pipeline` needs to accept a `std::function<void(const std::string&, bool)> alert_callback` so it can route messages back up to Java.

3. **Raw Pointers in Decision Engine (Memory/Safety)**:
   In `decision_engine.cpp`, you are dynamically allocating `Alert` objects (`new Alert()`) and manually `delete`ing them later. In modern C++, since `Alert` is just a small struct containing a few strings, it would be much safer and more performant to return `std::optional<Alert>` or return by value to avoid heap fragmentation and memory leaks.

### 🚧 What is Left / Incomplete

1. **Android Camera Integration**:
   The JNI `start` function takes an Android `Surface` (for drawing) and an `AssetManager`, but it completely ignores them. The `Pipeline` currently tries to use OpenCV's `cv::VideoCapture(0)`, which won't reliably work on modern Android devices without permissions/Camera2 API bindings. Furthermore, without using `ANativeWindow_fromSurface`, the C++ code has no way to draw the annotated frames back to the phone screen.

2. **Language Toggling on Mobile**:
   On desktop, the language is toggled by pressing the `'h'` key (`cv::waitKey`). On a phone, this won't work. The JNI bridge needs a `toggle_language()` binding connected to a UI button in Java.

### 🌟 "Bonus" Senior Recommendations

If you want to take this to the next level (production quality):

1. **Enable Hardware Acceleration (NPU/NNAPI)**:
   Right now, ONNX Runtime defaults to the CPU. You can instantly boost FPS on Android and save battery by appending the NNAPI Execution Provider to the session options in `detector.cpp` and `depth_estimator.cpp`:
   ```cpp
   #ifdef __ANDROID__
   uint32_t nnapi_flags = 0;
   OrtSessionOptionsAppendExecutionProvider_Nnapi(opts, nnapi_flags);
   #endif
   ```

2. **INT8 Model Quantization**:
   YOLOv8n is ~12MB in FP32. If you export it with INT8 quantization, it drops to ~3MB and runs significantly faster on ARM processors.

3. **Smart Alert Deduplication**:
   If there are 3 people ahead, the system might try to announce "Person ahead" multiple times. You could add logic in `DecisionEngine` to aggregate identical classes in the same zone: *"3 people ahead"*.

4. **Velocity Smoothing**:
   In `tracker.cpp`, velocity is calculated over just the time difference between the current and last frame. This can cause jittery bounding box predictions. Wrapping this in an Exponential Moving Average (EMA) would make tracking much smoother.

5. **Battery Optimization**:
   The `while(running_)` loop in `pipeline.cpp` spins as fast as possible. If the AI processing skips frames and the camera buffer hasn't updated, the thread will burn CPU cycles polling. Adding a small `std::this_thread::sleep_for(std::chrono::milliseconds(5))` when the camera buffer is empty will prevent the CPU from pegging at 100%.

Overall, it's a great C++ port! The AI logic is 90% there, but the "glue" connecting the C++ engine to the Android OS (Camera, Display, and Audio callbacks) is what needs the most love right now. Let me know if you want me to help implement any of these fixes!
