#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOBILE_DIR="$(dirname "$SCRIPT_DIR")"
THIRD_PARTY="$MOBILE_DIR/third_party"

echo "==> Downloading dependencies for AI Navigation Assistant (Mobile C++ port)"

# ---- ONNX Runtime (Linux x86_64 for desktop testing) ----
ONNX_VERSION="1.17.1"
ONNX_URL="https://github.com/microsoft/onnxruntime/releases/download/v${ONNX_VERSION}/onnxruntime-linux-x64-${ONNX_VERSION}.tgz"
ONNX_DIR="$THIRD_PARTY/onnxruntime"

if [ ! -d "$ONNX_DIR/lib" ]; then
    echo "==> Downloading ONNX Runtime ${ONNX_VERSION} for Linux..."
    mkdir -p "$THIRD_PARTY"
    wget -q --show-progress "$ONNX_URL" -O /tmp/onnxruntime.tgz
    mkdir -p "$ONNX_DIR"
    tar xzf /tmp/onnxruntime.tgz -C "$ONNX_DIR" --strip-components=1
    rm /tmp/onnxruntime.tgz
    echo "    ONNX Runtime installed at $ONNX_DIR"
else
    echo "    ONNX Runtime already present at $ONNX_DIR"
fi

# ---- OpenCV (system) ----
echo "==> Checking OpenCV..."
if pkg-config --exists opencv4 2>/dev/null; then
    echo "    OpenCV found via pkg-config"
elif dpkg -l libopencv-dev 2>/dev/null | grep -q '^ii'; then
    echo "    OpenCV found (libopencv-dev)"
elif pacman -Q opencv 2>/dev/null; then
    echo "    OpenCV found (pacman)"
else
    echo "    WARNING: OpenCV not detected. Install with:"
    echo "      sudo pacman -S opencv"
    echo "      sudo apt install libopencv-dev"
fi

# ---- yaml-cpp ----
echo "==> Checking yaml-cpp..."
if pkg-config --exists yaml-cpp 2>/dev/null; then
    echo "    yaml-cpp found via pkg-config"
else
    echo "    yaml-cpp will be fetched by CMake (FetchContent)"
fi

echo ""
echo "==> All dependencies ready!"
echo "==> Build with:"
echo "    mkdir -p mobile/build && cd mobile/build"
echo "    cmake .. -DONNXRUNTIME_ROOT=$ONNX_DIR"
echo "    make -j\$(nproc)"
