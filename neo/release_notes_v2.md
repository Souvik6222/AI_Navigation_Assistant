# AI Navigation Assistant - v0.0.2-alpha

This release addresses severe mobile-specific bugs affecting bounding box alignment, coordinate mapping accuracy, false positives, and raw frame rates on Android.

### Highlights & Fixes

- **Square Camera Viewport & Simplified Mapping:**
  - Replaced the full-screen `FrameLayout` with a structured `ConstraintLayout`.
  - Constrained the `PreviewView` to a 1:1 square ratio (`app:layout_constraintDimensionRatio="H,1:1"`) centered vertically in the available viewport.
  - Aligned the `OverlayView` to the exact same square, eliminating complex device-dependent coordinate offsets and resolving the "floating/offset boxes" issue. Bounding boxes are now drawn via a clean, linear scale.

- **Physical Sensor Rotation Processing:**
  - Addressed the CameraX sensor rotation limitation. Phone camera sensors naturally capture landscape frames (e.g., 1280x720) even when held in portrait mode, causing YOLO to process sideways images.
  - Passed the camera's `rotationDegrees` from CameraX through JNI to OpenCV, which physically rotates the matrix (`cv::rotate`) before cropping and feeding it upright to YOLO.

- **Eliminated 320x240 Squishing:**
  - Resolved a critical bug where the Android JNI configuration defaulted the C++ pipeline's processing size to `320x240`.
  - This was squishing the cropped square frame into a rectangle, which YOLO then stretched back to a square—deforming real-world objects and shrinking bounding box heights.
  - Forced the Android configuration to a clean `640x640` to match YOLO's native resolution.

- **Indoor Whitelist & False Positive Filtering:**
  - Fixed a JNI config issue where the class whitelist was not parsed, enabling all 80 COCO classes on Android. This led to false alarms (e.g., office chairs being detected as "horses" or other outdoor animals).
  - Hardcoded an indoor/navigation whitelist (person, laptop, chair, bench, etc.) directly into the JNI initialization code.

- **Performance & FPS Tuning:**
  - Switched the default model from `yolov8s.onnx` (43MB) to `yolov8n.onnx` (12MB), achieving a ~3x speedup on mobile CPUs.
  - Lowered the YOLO confidence threshold from `0.80` to `0.50` to maintain solid detection rates for office chairs while keeping noise low.
  - Configured NMS IoU threshold to `0.40` to suppress duplicate bounding box overlaps.
