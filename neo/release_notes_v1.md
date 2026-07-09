# AI Navigation Assistant - v0.0.1-alpha

First working version of the complete C++ port for Android and Desktop (Linux/Windows). This release migrates the core object detection and depth estimation pipeline away from Python's GIL bottleneck, achieving true multithreading with ONNX Runtime C++.

## Technical Changelog & Architectural Fixes

### 1. Camera Initialization Parsing Issue
- **Bug:** Providing an IP camera URL (`http://192.168.x.x:8080/video`) via YAML or the interactive prompt caused a GStreamer `assertion 'GST_IS_BIN (bin)' failed` crash or fell back to hardcoded models.
- **Fix:** Refactored `cam_index` (`int`) to `cam_source` (`std::string`). Added a `trim()` whitespace stripping function to prevent `std::getline` from absorbing stray tabs/spaces which corrupted the URL stream before hitting OpenCV's `cv::VideoCapture`.

### 2. MiDaS Depth Estimator Tensor Dimension Crash
- **Bug:** The pipeline would run fine on empty frames, but instantly core-dump with a `std::vector` out-of-bounds assertion (`Assertion '__n < this->size()' failed`) the exact millisecond YOLOv8 detected an object and triggered MiDaS.
- **Root Cause:** The C++ code strictly assumed the ONNX model would return a 4-dimensional tensor (`[Batch, Channels, Height, Width]`). However, due to PyTorch export variations (specifically when `dynamo=False` is used to bypass TorchDynamo compiler errors on MiDaS), it returned a squeezed 3-dimensional tensor (`[Batch, Height, Width]`).
- **Fix:** Implemented dynamic tensor shape checking in `depth_estimator.cpp` to gracefully route `output_shape[2]` and `output_shape[3]` vs `output_shape[1]` and `output_shape[2]` depending on `output_shape.size()`.

### 3. Android 11 NNAPI Delegate Concurrency Bug
- **Bug:** Android 11 NNAPI crashed with a CHECK failure `mOutputIndexes.size()=0` inside `libneuralnetworks.so` when running both YOLOv8 and MiDaS concurrently on the NPU.
- **Fix:** Disabled NNAPI delegation and forced CPU execution. Pinned intra-op threads to `6` to spread heavy convolutions specifically across the Snapdragon 765G's Kryo 475 cores (avoiding the thread-pool thrashing bottleneck seen on 20+ core desktop CPUs).

*(Note: This version uses `yolov8s.onnx` and has known FPS/bounding box distortion issues on mobile due to 9:16 portrait aspect ratios being squashed into 640x640. Fixed in v0.0.2-alpha).*
