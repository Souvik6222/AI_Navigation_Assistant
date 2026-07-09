# Release Notes v0.0.4-alpha (v4)

## Core Features & Improvements

- **Real-Time Depth-Only Wall & Obstacle Detection**
  Overhauled the computer vision C++ pipeline to add a pure depth-based obstacle fallback. The system now monitors the central 30% area of the raw float depth map (`0.0–1.0` range). If the average value in this center patch exceeds a proximity threshold (set to `0.65`), it injects a virtual `wall` detection. This allows the system to warn the user about featureless, flat white walls that standard YOLO object detection fails to recognize.
- **Smart TTS & LLM Audio Prioritization**
  Added concurrency protection to prevent navigation alerts from interrupting detailed LLM vision scene descriptions. When a vision description is spoken, it locks out standard navigation TTS alerts for 8 seconds (`VISION_LOCK_MS`). Critical warnings under 2 meters (`TTS URGENT`) are still allowed to instantly break through to ensure safety.
- **Navigation Alert Latency Reductions**
  Reconfigured the Text-to-Speech call mechanism in Java to use `QUEUE_FLUSH` instead of `QUEUE_ADD` for all standard alerts. This immediately drops the 5-second lag backlog, ensuring the speaker always says the most current, real-time alert rather than walking through a stale queue of historical frame detections.
- **Dynamic Multilingual LLM Prompts (Hindi/English)**
  Aligned the remote LLM vision triggers with the user's local language settings. If the user toggles the application to Hindi, the prompt instructs the LLM to output the response directly in Hindi, removing language mismatches. The prompt was also optimized to strictly enforce a one-sentence brief limit to speed up audio delivery.

## Housekeeping & Fixes

- **RHVoice Connectivity Resolution (Android 11+ Package Visibility)**
  Added a `<queries>` tag to `AndroidManifest.xml` declaring standard `TTS_SERVICE` intents and the `com.github.olga_yakovleva.rhvoice.android` package. This resolves the Android package visibility filtering rules that previously blocked the app from seeing or binding to the RHVoice engine.
- **Groq Reasoning Effort Tuning**
  Automatically injected the `"reasoning_effort": "none"` payload parameter into API requests targeting Groq (under the new default `qwen/qwen3.6-27b` model) to skip thinking cycles and reduce latency.
- Incremented `versionCode` to `4` and `versionName` to `0.0.4-alpha` in both the Gradle build settings and the `AndroidManifest.xml`.
- Replaced the generated output binary name with `ai_navigation_assistant-v0.0.4-alpha.apk`.
