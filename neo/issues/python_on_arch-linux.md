# 📄 Setup Guide: AI Navigation Assistant (Python 3.12 + CUDA 12)

## 🚨 The Problem
- **System Default**: Arch Linux defaults to **Python 3.14**, but the project requires **Python 3.12**.
- **Disk Space**: Standard `venv` copies all packages for every environment, causing massive duplication (3–4 GB per project, 10+ GB total).
- **Missing Dependencies**: Dynamic model loading (MiDaS) requires specific libraries (`timm`) not installed by default.

## ✅ The Solution
We used **`uv`**, a modern Rust-based package manager that:
1.  **Manages Python Versions**: Automatically downloads and uses Python 3.12 without AUR/manual compilation.
2.  **Saves Disk Space**: Uses a **global cache** with hard links. Packages like PyTorch are downloaded **once** and shared across all projects.
3.  **Speed**: Installs dependencies 10–100x faster than `pip`.

---

## 🛠️ All Commands Used (Step-by-Step)

### 1. Install `uv`
Install the tool itself (one-time setup).
```bash
sudo pacman -S uv
```

### 2. Create the Virtual Environment
Creates a `venv312` folder using **Python 3.12**. `uv` handles the Python installation automatically.
```bash
uv venv venv312 --python 3.12
```

### 3. Install Dependencies
Installs PyTorch (with CUDA 12 auto-detection), Ultralytics, ONNX, and the missing `timm` library.
```bash
# Activate is NOT required for uv pip, but good for verification
source venv312/bin/activate 

# Install Core AI Libraries
uv pip install torch torchvision torchaudio

# Install Project Dependencies
uv pip install ultralytics onnx onnxruntime-gpu

# Fix Missing Dependency (MiDaS requires this)
uv pip install timm
```

### 4. Run the Project
Execute the script using the isolated environment.
```bash
# Recommended: Run without manual activation
uv run --python 3.12 python main.py

# OR if already activated:
python main.py
```

### 5. Update Requirements File (Best Practice)
Save the exact working versions to `requirements.txt` so others can replicate this easily.
```bash
uv pip freeze > requirements.txt
```

---

## 🔍 Verification
To confirm everything is working (CUDA, Python Version, Modules):
```bash
uv run --python 3.12 python -c "import torch, timm; print(f'Python: {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}'); print('timm: OK')"
```

## 📂 Project Structure Note
- **`venv312/`**: Contains the isolated environment (safe to delete and recreate).
- **`~/.cache/uv/`**: Contains the global package cache (shared across all projects, do not delete unless necessary).
- **`.gitignore`**: Ensure `venv312/` is added to `.gitignore` so you don't commit gigabytes of data to Git.

