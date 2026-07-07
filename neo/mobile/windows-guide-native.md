# Native Windows Compilation Guide (Without WSL)

If you are running Windows and want to compile the PC test binary natively, follow this guide. Native compilation ensures maximum performance on Windows and allows direct access to all local USB webcams without virtualization barriers.

---

## 1. Prerequisites

You will need to install the following tools:
1. **Visual Studio (2022 recommended)**: Install the "Desktop development with C++" workload. This provides the MSVC compiler.
2. **CMake**: Download the Windows installer from `cmake.org`.
3. **vcpkg** (C++ Package Manager): This is the easiest way to get OpenCV and libcurl on Windows natively.

To install `vcpkg`, open PowerShell:
```powershell
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg integrate install
```

---

## 2. Installing Dependencies

Using `vcpkg`, install the required libraries. This process might take a while as it compiles OpenCV from source.

```powershell
vcpkg install opencv4[core,dnn,videoio,highgui]:x64-windows
vcpkg install curl:x64-windows
vcpkg install yaml-cpp:x64-windows
```

### ONNX Runtime
`vcpkg` has an onnxruntime package, but it is often easier to download the pre-compiled Windows binaries directly from Microsoft:
1. Go to the [ONNX Runtime GitHub Releases](https://github.com/microsoft/onnxruntime/releases).
2. Download `onnxruntime-win-x64-1.16.x.zip`.
3. Extract it to `C:\onnxruntime`.

---

## 3. Visual Studio Code (VS Code) Workflow

If your friend has the MSVC compiler installed, they do **not** need to use the heavy Visual Studio IDE. They can use **VS Code** seamlessly.

### Setup in VS Code:
1. Open VS Code and install the **CMake Tools** and **C/C++** extensions by Microsoft.
2. Open the `AI_Navigation_Assistant\mobile` folder in VS Code.
3. Create a `.vscode/settings.json` file to tell CMake where to find `vcpkg` and `ONNX Runtime`:
```json
{
    "cmake.configureArgs": [
        "-DCMAKE_TOOLCHAIN_FILE=C:/path/to/vcpkg/scripts/buildsystems/vcpkg.cmake",
        "-DONNXRUNTIME_ROOT_DIR=C:/onnxruntime"
    ]
}
```
4. Look at the bottom blue status bar in VS Code. Click **No Kit Selected** and choose your **Visual Studio Build Tools Release (amd64)**.
5. Click the **Build** button (or press `F7`). VS Code will automatically run CMake and compile the project using MSVC in the background!
6. Click the **Play / Debug** button to launch the executable directly inside the VS Code terminal.

---

## 4. Fixing the Windows Path Issue (CRITICAL GOTCHA)

Windows uses backslashes (`\`) for file paths, but backslashes act as escape characters in YAML and C++ strings. 

**Rule:** When configuring your `config.yaml` on Windows, you **MUST** use forward slashes (`/`) or double backslashes (`\\`).

```yaml
# ✅ CORRECT (Forward slashes)
detection:
  model_path: "C:/Users/YourName/AI_Navigation_Assistant/mobile/models/yolov8s.onnx"

# ✅ CORRECT (Double backslashes)
detection:
  model_path: "C:\\Users\\YourName\\AI_Navigation_Assistant\\mobile\\models\\yolov8s.onnx"

# ❌ WRONG (Will crash YAML parser instantly)
detection:
  model_path: "C:\Users\YourName\models\yolov8s.onnx"
```

---

## 5. Compiling via Command Line (PowerShell Alternative)

If you don't want to use VS Code, you can compile via the terminal:

1. Open **Developer PowerShell for VS 2022** (Search for it in the Start Menu).
2. Navigate to the mobile directory:
   ```powershell
   cd C:\Users\YourName\AI_Navigation_Assistant\mobile
   mkdir build-win
   cd build-win
   ```
3. Run CMake and Build:
   ```powershell
   cmake .. -DCMAKE_TOOLCHAIN_FILE="C:\path\to\vcpkg\scripts\buildsystems\vcpkg.cmake" -DONNXRUNTIME_ROOT_DIR="C:\onnxruntime"
   cmake --build . --config Release
   ```

---

## 6. Running the Application

Once compiled, your executable will be located at `build-win\Release\ai_navigation_assistant.exe`.

Before running it, you must copy the `.dll` files next to your `.exe` so Windows can dynamically load them:
1. Copy `onnxruntime.dll` from `C:\onnxruntime\lib` to your `Release` folder.
2. Copy `opencv_*.dll`, `libcurl.dll`, and `yaml-cpp.dll` from `vcpkg\installed\x64-windows\bin` to your `Release` folder.

Run the binary:
```powershell
.\Release\ai_navigation_assistant.exe
```

Because you are running natively on Windows, entering `0` at the interactive camera prompt will successfully connect to your laptop's integrated USB webcam immediately!
