# Goal Description

Implement the remaining bonus features (Bonus #3, #4, and #5) in the C++ backend and redesign the Android UI to include a bottom floating action bar with Vision, API, and Settings options.

## Answer: Which `onnxruntime` to install?

Since you are running Arch Linux on a machine with an NVIDIA GPU (Intel Core i7 + RTX GPU running `torch-2.12.1+cu130` as seen in your earlier logs), I recommend installing **`onnxruntime-cuda`**. 

This will allow the C++ desktop build to utilize your NVIDIA GPU via the CUDA Execution Provider for maximum FPS during local testing. If you prefer a simpler setup without CUDA dependencies for desktop testing, you can choose `onnxruntime-cpu`. (Note: This choice only affects your local desktop build; the Android build will still use the NNAPI we configured earlier).

## Open Questions

- **Android UI Functionality**: For the "API Change" and "Settings" buttons on the floating bar, should they open placeholder dialogs for now? The C++ backend currently doesn't have an LM Studio/Llama integration yet, so the API button would just be a UI stub until that feature is ported from Python.

## Proposed Changes

---

### C++ Core Logic

#### [MODIFY] [tracker.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/tracker.cpp)
- **Bonus #4 (Velocity Smoothing)**: Update the bounding box velocity calculation (`vel_x`, `vel_y`) to use an Exponential Moving Average (EMA). Instead of relying solely on the instantaneous velocity between the current and previous frame (which causes jitter), we will blend the new velocity with the previous velocity using an EMA alpha weight (e.g., `0.3`).

#### [MODIFY] [decision_engine.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/decision_engine.cpp)
- **Bonus #3 (Smart Alert Deduplication)**: Refactor `DecisionEngine::evaluate()` to group valid tracked objects by their `(label, direction)`.
- If multiple objects of the same class (e.g., "person") are in the same zone (e.g., "ahead"), aggregate them into a single plural alert (e.g., "3 people ahead").
- Provide simple pluralization rules for English (adding 's', with exceptions for person->people) and Hindi phrasing.

#### [MODIFY] [pipeline.cpp](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/src/pipeline.cpp)
- **Bonus #5 (Battery Optimization)**: Ensure the camera polling loop uses `std::this_thread::sleep_for` correctly. *(Note: I proactively added a 10ms sleep during the zombie thread fix earlier, but I will review it to ensure it perfectly matches the battery optimization criteria.)*

---

### Android UI Redesign

#### [MODIFY] [activity_main.xml](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/res/layout/activity_main.xml)
- Implement a floating bottom bar (`LinearLayout` wrapped in a `CardView` with rounded corners and semi-transparent monochrome background) aligned to the bottom.
- Add three buttons to the floating bar:
  1. **Vision**: Main camera detection mode (will include a camera swap icon).
  2. **API**: Switch between local YOLO and remote Llama/LM Studio.
  3. **Settings**: Open settings (Language, Dark Mode, Licenses).
- Remove the old top-right language toggle button.

#### [MODIFY] [MainActivity.java](file:///home/vista/class/class_project/AI_Navigation_Assistant/mobile/android/src/com/navigation/assistant/MainActivity.java)
- Add logic to auto-hide the bottom floating bar after 5 seconds of inactivity.
- Add a touch listener to the `SurfaceView` to reveal the floating bar when the user taps the screen.
- Wire the UI buttons to show simple Android `BottomSheetDialog` or `AlertDialog` popups for the API and Settings menus, maintaining a clean monochrome look.
- Support toggling the Android app's Day/Night mode via the Settings dialog.

## Verification Plan

### Automated Tests
- Build the C++ pipeline locally to ensure syntax and linking remain correct for `tracker.cpp` and `decision_engine.cpp`.

### Manual Verification
- Rebuild the Android APK using gradle to verify the new XML layouts and Java logic compile correctly.
