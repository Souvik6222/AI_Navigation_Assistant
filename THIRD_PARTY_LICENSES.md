# Third-Party Software Notices

AI Navigation Assistant incorporates components from the following open-source
projects. Their respective licenses are reproduced below.

---

## 1. YOLOv8 (Ultralytics)

**Used for:** Real-time object detection (yolov8n.onnx model weights)
**License:** GNU Affero General Public License v3.0 (AGPL-3.0)
**Source:** https://github.com/ultralytics/ultralytics

> ⚠️  IMPORTANT NOTICE
> The pre-trained YOLOv8 model weights bundled with this application are
> distributed by Ultralytics under AGPL-3.0. The ONNX model file itself
> (yolov8n.onnx) is considered a derivative work of the training codebase.
> This project uses the model solely as an inference artifact (no training
> code is included or distributed). For any commercial use of this project,
> you are responsible for ensuring compliance with Ultralytics' licensing
> terms or obtaining a commercial license from:
> https://www.ultralytics.com/license

---

## 2. ONNX Runtime (Microsoft)

**Used for:** Running YOLO and MiDaS inference on-device
**License:** MIT License
**Source:** https://github.com/microsoft/onnxruntime

    MIT License

    Copyright (c) Microsoft Corporation

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject
    to the following conditions:

    The above copyright notice and this permission notice shall be included
    in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## 3. OpenCV (OpenCV Foundation)

**Used for:** Camera frame processing, image rotation, color conversion,
             center-crop, and resize operations
**License:** Apache License 2.0
**Source:** https://github.com/opencv/opencv

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

---

## 4. MiDaS (Intel ISL)

**Used for:** Monocular depth estimation (midas_v21_small_256.onnx)
**License:** MIT License
**Source:** https://github.com/isl-org/MiDaS

    MIT License

    Copyright (c) 2019 Intel ISL (Intel Intelligent Systems Lab)

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject
    to the following conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## 5. yaml-cpp

**Used for:** Parsing config.yaml on the PC runtime
**License:** MIT License
**Source:** https://github.com/jbeder/yaml-cpp

    Copyright (c) 2008-2015 Jesse Beder.

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject
    to the following conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## 6. AndroidX / CameraX (Google)

**Used for:** Camera2 API abstraction, preview stream, and image analysis
             on Android
**License:** Apache License 2.0
**Source:** https://developer.android.com/jetpack/androidx

    Licensed under the Apache License, Version 2.0.
    See: http://www.apache.org/licenses/LICENSE-2.0

---

## 7. Android ConstraintLayout (Google)

**Used for:** UI layout to constrain the 1:1 square camera preview
**License:** Apache License 2.0
**Source:** https://developer.android.com/reference/androidx/constraintlayout

    Licensed under the Apache License, Version 2.0.
    See: http://www.apache.org/licenses/LICENSE-2.0
