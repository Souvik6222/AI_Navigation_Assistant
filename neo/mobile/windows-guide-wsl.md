# Windows / WSL Guide for AI Navigation Assistant

If a teammate is on a Windows machine, there are a few different ways they can run and compile the C++ port.

---

## 1. Running on WSL (Windows Subsystem for Linux)

Since you are running Arch Linux, and your friend has Arch Linux installed on WSL, **they can compile and run this identically to a native Linux machine!**

### Step 1: Install Dependencies via Pacman
Before compiling, they must install the required C++ libraries. Run this in the WSL Arch terminal:
```bash
sudo pacman -Syu
sudo pacman -S base-devel cmake opencv onnxruntime curl yaml-cpp
```

### Step 2: Compile the Source Code
Navigate to the `mobile` directory inside the project, create a build directory, and use CMake to compile using all available CPU cores:
```bash
cd AI_Navigation_Assistant/mobile
mkdir build-wsl
cd build-wsl
cmake ..
make -j$(nproc)
```

### Step 3: Run the Application
You can launch the executable directly from the build folder. 
```bash
./ai_navigation_assistant
```

### Helpful Command Line Flags
If you want to override defaults without interactive prompts or editing files, use these flags:
- `./ai_navigation_assistant --help` : Show all available flags.
- `./ai_navigation_assistant --no-display` : Run in "headless" mode without the OpenCV video window (great for raw terminal output).
- `./ai_navigation_assistant --config /path/to/custom_config.yaml` : Point to a specific config file if launching from a different directory.

---

## ⚠️ Common Issues & Gotchas on WSL

### 1. Camera Passthrough
WSL natively does *not* easily pass through local USB webcams (`/dev/video0`). 
- **IP Cameras:** Using an IP camera (like DroidCam or an IP Webcam app via `http://192.168.x.x:8080/video`) works **flawlessly** out of the box in WSL because it operates over the network.
- **USB Webcams:** If they want to use `device_index: 0`, they must install **usbipd-win** on Windows to forward the physical USB camera into the WSL Linux kernel.

### 2. The Dirty CMakeCache Trap
If you ever move or rename the `build-wsl` folder, `make` will fail spectacularly with absolute path errors.
**Solution:** Wipe the build directory and reconfigure:
```bash
rm -rf *
cmake ..
make -j$(nproc)
```

### 3. Missing Config File
The C++ executable looks for `config.yaml` in the exact directory you run the command from. If you run `./ai_navigation_assistant` and there is no config file next to it, it will fall back to hardcoded models (which likely don't exist) and crash. Always ensure a `config.yaml` sits right next to the `.exe`, or use the `--config` flag.

### 4. Running Android Studio (NDK/SDK) on WSL
Yes! You can absolutely compile the Android APK inside WSL. 
While running the full Android Studio IDE GUI inside WSL is possible (using WSLg), it can be slightly laggy. The standard workflow is:
1. Download the Command Line Tools (`sdkmanager`) inside WSL.
2. Install the NDK, CMake, and Build Tools via `sdkmanager`.
3. Use Gradle to compile the C++ Android App from the terminal:
   ```bash
   ./gradlew assembleDebug
   ```
   
---

## 2. Transferring Binaries Directly
Because the CPU architecture is the same (x86_64) and the OS is Arch Linux on both ends, you actually don't *have* to recompile. You can simply zip your `/mobile/runtime-pc/binaries/build-pc` folder, send it to them, ensure they ran the pacman dependency command above, and it will execute perfectly.
