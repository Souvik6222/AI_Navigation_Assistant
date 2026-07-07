Since you are using **C++**, you cannot simply "install" the ARM version on your PC to link against it. The `pacman` package manager installs libraries for the *current* machine architecture (x86_64).

Here is the clarified **1st Option (Cross-Compilation)** workflow for C++:

### The Concept
You keep your PC setup for **x86_64 (CUDA)**. To build for **Mobile (ARM)**, you use a **Cross-Compiler**. This is a special compiler installed on your PC that generates ARM code instead of PC code.

### Step-by-Step Guide

#### 1. Install the PC Version (CUDA)
In your current terminal prompt, select **Option 2** (`onnxruntime-cuda`).
*   This gives you the headers (`/usr/include/onnxruntime`) and libraries (`/usr/lib/libonnxruntime.so`) for your **PC**.
*   You will use these to compile and test your code locally on your PC.

#### 2. Install the Cross-Compiler
Install the ARM toolchain on your PC. This allows you to compile C++ code for ARM devices.
```bash
sudo pacman -S aarch64-linux-gnu-gcc aarch64-linux-gnu-gcc-libs
```
*(Note: If your mobile device is 32-bit ARM like an old Raspberry Pi, use `arm-linux-gnueabihf-gcc` instead).*

#### 3. Get ARM Libraries (Do NOT use pacman)
You cannot use the `onnxruntime` package from pacman for the mobile build. You have two choices:
*   **Option A (Easiest):** Download pre-built ARM binaries from the [ONNX Runtime GitHub Releases](https://github.com/microsoft/onnxruntime/releases). Look for a file like `onnxruntime-linux-aarch64-<version>.tgz`. Extract it to a folder in your project (e.g., `./libs/arm64`).
*   **Option B (Advanced):** Build ONNX Runtime from source on your PC using the `--arm64` flag (requires cloning the repo and running `./build.sh --arm64`).

#### 4. Compile for Mobile
When building your C++ project for the mobile device, you must tell your build system (CMake/Make) to:
1.  Use the **ARM compiler** (`aarch64-linux-gnu-g++`).
2.  Link against the **ARM libraries** you downloaded in Step 3 (not the ones in `/usr/lib`).

**Example with CMake:**
```bash
# Create a build folder for ARM
mkdir build-arm && cd build-arm

# Configure CMake to use the ARM toolchain and custom library path
cmake .. \
  -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc \
  -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++ \
  -DONNXRUNTIME_INCLUDE_DIR=/path/to/extracted/arm/include \
  -DONNXRUNTIME_LIBRARY=/path/to/extracted/arm/lib/libonnxruntime.so

# Build
make
```
The resulting executable will run on your mobile device, not your PC.

### Summary
*   **PC Development:** Select **Option 2** in pacman. Compile normally.
*   **Mobile Deployment:** Install `aarch64-linux-gnu-gcc`. Download ARM binaries manually. Compile using the cross-compiler flags pointing to those manual binaries.



