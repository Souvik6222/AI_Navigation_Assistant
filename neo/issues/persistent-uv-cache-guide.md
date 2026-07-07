Here is a comprehensive guide for moving and persisting the `uv` cache.

### Suggested Filename
**`uv-cache-setup.md`** or **`persistent-uv-cache-guide.md`**

---

# 📦 Guide: Moving `uv` Cache to Persistent Storage

## 🎯 Why Move the Cache?
By default, `uv` stores downloaded packages in `~/.cache/uv`.
- **Problem**: This folder grows rapidly (often 5–10 GB+). Users who regularly clean `~/.cache` force `uv` to re-download everything, wasting time and bandwidth.
- **Solution**: Move the cache to a dedicated folder (e.g., `~/uv-cache-persistent`) that is excluded from cleanup scripts. `uv` uses hard links, so this folder is the **single source of truth** for all your projects.

## 🚀 Step-by-Step Migration

### 1. Create the New Directory
Create a folder outside of `.cache` (no dot prefix).
```bash
mkdir ~/uv-cache-persistent
```

### 2. Move Existing Data (Optional)
If you already have packages downloaded, move them to the new location to avoid re-downloading.
```bash
# Move contents from old cache to new folder
mv ~/.cache/uv/* ~/uv-cache-persistent/
```
*(If `~/.cache/uv` is empty or doesn't exist, you can skip this step.)*

### 3. Configure Your Shell
Add the `UV_CACHE_DIR` environment variable to your shell's configuration file so `uv` always uses the new location. Choose **only one** of the following blocks based on your shell.

#### 🔹 For Bash (`~/.bashrc`)
```bash
echo 'export UV_CACHE_DIR="$HOME/uv-cache-persistent"' >> ~/.bashrc
source ~/.bashrc
```

#### 🔹 For Zsh (`~/.zshrc`)
```bash
echo 'export UV_CACHE_DIR="$HOME/uv-cache-persistent"' >> ~/.zshrc
source ~/.zshrc
```

#### 🔹 For Fish (`~/.config/fish/config.fish`)
```bash
echo 'set -x UV_CACHE_DIR "$HOME/uv-cache-persistent"' >> ~/.config/fish/config.fish
source ~/.config/fish/config.fish
```

### 4. Verify the Change
Run the following command to confirm `uv` is pointing to the new directory:
```bash
uv cache dir
```
**Expected Output:**
```text
/home/vista/uv-cache-persistent
```

## 🧹 Maintenance & Cleanup
- **Safe to Clean**: You can now safely run `rm -rf ~/.cache/*` without losing your Python packages.
- **Clearing the Cache**: If you ever need to force a re-download (e.g., to fix corruption), run:
  ```bash
  uv cache clean
  ```
  *(This will clear the content inside `~/uv-cache-persistent`, not your whole home directory.)*

## 📝 Summary of Commands
| Action | Command |
| :--- | :--- |
| **Create Folder** | `mkdir ~/uv-cache-persistent` |
| **Move Data** | `mv ~/.cache/uv/* ~/uv-cache-persistent/` |
| **Verify** | `uv cache dir` |
| **Clean Cache** | `uv cache clean` |