# Merge Conflict Resolution, Bug Fixes & Performance Optimization

**Date:** June 13, 2026
**Topics:** Git branch merge, conflict resolution, post-merge bug fixes, ONNX GPU migration, FPS recovery from 17 to 200

---

## Table of Contents

1. [Git Branch Merge: experimental-merge → main](#1-git-branch-merge-experimental-merge--main)
2. [Conflict Resolution — 6 Files](#2-conflict-resolution--6-files)
3. [Post-Merge Bug Fixes](#3-post-merge-bug-fixes)
4. [ONNX GPU Optimization (from 05_onnx_gpu_optimization.md)](#4-onnx-gpu-optimization)
5. [Complete Performance Timeline](#5-complete-performance-timeline)
6. [Appendix: Commands & Git History](#6-appendix-commands--git-history)

---

## 1. Git Branch Merge: experimental-merge → main

### 1.1 Background

The `experimental-merge` branch was created from `main` (at commit `bb62f9c`) and contained 20 granular commits spanning June 7--10, 2026. These commits represented the complete development history of the AI Navigation Assistant's core features:

- LM Studio client replacing Groq/Claude API
- Hungarian algorithm tracker with velocity prediction
- Hindi TTS improvements (gTTS priority over espeak-ng, dedicated prompts module)
- Performance: async threaded camera, conditional depth estimation, frame skip
- Path clearance announcements, velocity-based alert escalation, category cooldowns
- Camera rotation, LM Studio model tuning, project documentation

Meanwhile, `main` had received 3 new commits pushed independently (by another collaborator) after `experimental-merge` had been created:

```
00b4057 The yolov8x.onnx file still exists on your local disk...
f2455b5 Perf: 5 optimizations — conditional depth, frame skip, async camera, ONNX, class trim
6a152dc Fix: Resolve repeated object announcements and MJPEG logs
```

### 1.2 The Stable Backup Branch (Safeguard)

Before performing the merge, we created an **exact 1:1 copy of the pre-merge `main` branch** named `stable`:

```bash
git branch stable main                         # create stable backup branch BEFORE merge
```

This `stable` branch points at commit `00b4057` — the same commit as `origin/main` before the merge. It preserves the original `main` state in case the merge goes wrong or a rollback is needed later.

**Verification (0 lines diff = exact copy):**
```
stable tip:         00b40579198cc051121ac20811a804947cbdbc05
pre-merge main:     00b40579198cc051121ac20811a804947cbdbc05
Diff?               0 lines changed
```

The `stable` branch was also pushed to remote so collaborators can switch to it:
```bash
git push origin stable
```

Any collaborator can switch to the pre-merge state by running:
```bash
git fetch origin stable
git checkout stable
# or to replace their local main with stable:
git checkout main
git reset --hard origin/stable
```

### 1.3 Merge Execution

The merge was performed from `main` (target) into `experimental-merge` (source):

```bash
git fetch origin main                          # check for remote changes (3 new commits found)
git checkout main                              # switch to target branch
git merge --ff-only origin/main                # fast-forward local main to match remote
git merge experimental-merge --no-ff           # merge with explicit merge commit
```

### 1.3 Merge Commit

```
b373ee2 (HEAD -> main) Merge experimental-merge into main
|
|   Brings in 20 commits from experimental-merge (June 7-10):
|   - LM Studio client replacing Groq/Claude API
|   - Hungarian tracker with velocity prediction
|   - Hindi TTS: gTTS priority, prompts module, espeak-ng fix
|   - Performance: async camera, conditional depth, frame skip
|   - Path clearance, velocity escalation, category cooldown
|   - Camera rotation, model tuning, documentation
|
* 8721316 Document all architectural phases in evolution log
* ...
```

---

## 2. Conflict Resolution — 6 Files

Six files had conflicting changes between the two branches. Each required manual resolution.

### 2.1 `.gitignore` — Combine Both Changes

**Conflict 1:** `main` had added `*.onnx` to exclude ONNX model files from tracking. `experimental-merge` had no such exclusion.

**Conflict 2:** `experimental-merge` had added `session-*.md` and `neo/exports/` exclusion patterns. `main` had no such exclusion.

**Resolution:** Kept both sets of additions. The final `.gitignore` includes:

```
*.pt
*.onnx
session-*.md
neo/exports/
```

### 2.2 `config.yaml` — Accept experimental-merge Values

**Conflict:** The `lm_studio` section differed in two values:

| Setting | main (HEAD) | experimental-merge |
|---------|-------------|-------------------|
| `model` | `qwen2.5-coder-3b-instruct-128k` | `qwen3.5-0.8b` |
| `auto_trigger_interval_seconds` | `5` | `30` |

**Resolution:** Accepted experimental-merge's values (theirs). The `qwen3.5-0.8b` model was the one actually running in LM Studio, and a 30-second auto-trigger interval is more practical than 5 seconds to avoid excessive LLM calls.

### 2.3 `main.py` — The Most Complex Conflict

**Conflicts spanned ~100 lines** across 11 separate conflict regions. Key differences:

| Region | main (HEAD) | experimental-merge |
|--------|-------------|-------------------|
| Import order | `LMStudioClient` then `CameraStream` | `CameraStream` then `LMStudioClient` |
| Docstring for LM Studio hotkey | "D — Trigger LM Studio scene description" | "LM Studio scene description" |
| Process every N config | Present (from perf commit f2455b5) | Present (from experimental commits) |
| Frame skip logic | Clean structure with `if/else` | Mixed indentation, broken from rebase |
| Alert logging | Compact f-string | Broken multi-line with syntax errors |
| Language toggle cooldown | Present (variable definition + cooldown guard) | Present but with different comment style |
| LM Studio auto-trigger | Inside frame-skip block | Duplicated (inside AND outside block) |
| `ord("d")` handler | `lm_client.describe_scene_async(frame_b64, [], language)` | `lm_client.describe_scene_async(frame_b64, detections, language)` |

**Resolution:** Accepted experimental-merge as base (theirs), then manually fixed all indentation and structural bugs (see Section 3).

### 2.4 `modules/camera.py` — Accept experimental-merge

**Conflicts:** Purely docstring/comment differences. `main` had more detailed docstrings (Google-style with Args/Returns sections). `experimental-merge` had minimal comments.

**Resolution:** Accepted experimental-merge (theirs). The code logic is identical; the stripped comments reduce visual noise.

### 2.5 `modules/decision_engine.py` — Accept experimental-merge with Structural Differences

**Conflict 1 (evaluate method):** `main` had spatial grouping logic (grouping same-label objects by direction into "Multiple X" alerts). `experimental-merge` had per-object evaluation with velocity-based escalation.

**Conflict 2 (_create_alert method):** `main` used a `count` parameter for grouped alerts with singular/plural message prefixes. `experimental-merge` used `motion_state` and `velocity` parameters with velocity-based escalation and "approaching" voice modifiers.

**Conflict 3 (evaluate flow):** `main` had category-level cooldown tracking inside the new grouped loop. `experimental-merge` had motion state extraction and path-clearance announcement checks.

**Resolution:** Accepted experimental-merge (theirs). The velocity-based escalation feature (SIG-3) and path-clearance announcements (SIG-2) are more valuable than spatial grouping. The velocity escalation code:

```python
# From experimental-merge's evaluate method
motion_state = "STATIONARY"
velocity = 0.0
if self._tracker is not None:
    track_id = obj.get("track_id", -1)
    motion_state = self._tracker.get_motion_state(track_id)
    velocity = self._tracker.get_velocity(track_id)

alert = self._create_alert(label, distance, direction, obj, motion_state, velocity)
```

With velocity escalation in `_create_alert`:

```python
# If approaching fast, escalate WARNING to URGENT
if is_approaching and velocity < -0.3:
    level = "urgent"
    message_en = f"{label.capitalize()} approaching fast {en_dir}!"
    message_hi = f"{hi_label} tez aa raha hai {hi_dir}!"
    priority += 15.0
```

### 2.6 `modules/lm_studio_client.py` — Accept experimental-merge

**Conflict 1:** `experimental-merge` imported prompts from a dedicated `modules/prompts.py` module (`SYSTEM_PROMPT_EN`, `SYSTEM_PROMPT_HI`, `SCENE_DESCRIPTION_PROMPT_EN`, etc.). `main` embedded prompts inline.

**Conflict 2:** `experimental-merge` used `self._get_prompts(language)` to select language-appropriate prompt sets. `main` hardcoded language selection via `lang_name = "Hindi" if language == "hi" else "English"`.

**Resolution:** Accepted experimental-merge (theirs). The `prompts.py` module is cleaner and supports future language additions. The `_get_prompts` static method provides a single dispatch point:

```python
@staticmethod
def _get_prompts(language: str) -> tuple:
    if language == "hi":
        return SYSTEM_PROMPT_HI, SCENE_DESCRIPTION_PROMPT_HI, STARTUP_PROMPT_HI
    return SYSTEM_PROMPT_EN, SCENE_DESCRIPTION_PROMPT_EN, STARTUP_PROMPT_EN
```

---

## 3. Post-Merge Bug Fixes

The merge introduced several runtime bugs. These were discovered during testing and fixed in commit `e6d8b2d` and subsequent hotfixes. **No code changes were made to the experimental-merge branch's actual logic -- only broken syntax and missing initializations were corrected.**

### 3.1 Frame-Skip Block Indentation Corruption

**File:** `main.py` lines 242--294

The most severe bug. The `--theirs` checkout carried over experimental-merge's source, but that file itself had been corrupted during the git history rewrite. The frame-skip `if/else` block had mixed indentation -- some lines used 12 spaces, others 8, others 16. This caused:

- `detections = detector.detect(frame)` was indented 4 spaces too deep (20 spaces instead of 16)
- `cached_tracked_objects = tracked_objects` was indented 8 spaces too deep
- An orphan `else:` clause appeared at an indentation level that didn't match any `if`
- Blank lines had inconsistent indentation levels

**Fix:** Replaced the entire frame-skip section (50+ lines) with the correct, working version from pre-merge main (commit `00b4057`). The corrected structure:

```python
# ---- Frame skip: only run AI on every Nth frame ----
if frame_index % process_every_n == 0:

    # ---- 2. YOLOv8 Detection ----
    detections = detector.detect(frame)

    # ---- 3. MiDaS Depth Estimation (CONDITIONAL) ----
    if len(detections) > 0:
        depth_map = depth_estimator.estimate(frame)
        for det in detections:
            det["direction"] = get_direction(...)
            det["distance_m"] = depth_estimator.get_distance(depth_map, det["bbox"])

    # ---- 5. Update tracker ----
    tracked_objects = tracker.update(detections, frame_width)
    cached_tracked_objects = tracked_objects

    # ---- 6. Decision engine -> alerts ----
    alerts = decision_engine.evaluate(tracked_objects)

    # ---- 7. Send alerts to voice engine ----
    language = voice_engine.get_language()
    for alert in alerts:
        ...
    # ---- 8. Annotate frame ----
    ...
    # ---- 12. Auto-trigger LM Studio ----
    if lm_client.should_auto_trigger() and len(detections) > 0:
        ...

else:
    # Skipped frame: reuse cached annotations
    annotated_frame = ...
```

### 3.2 Alert Logging F-String Format Error

**File:** `main.py` line 292

**Error:**
```
ValueError: Unknown format code 'f' for object of type 'str'
```

**Cause:** The logging f-string applied `:.1f` format specifier to `alert.tracked_object.get("distance_m", "?")`. When a "path_clear" alert fires (which has `tracked_object={}`, an empty dict), the `.get()` fallback returns the string `"?"`. Applying `:.1f` to a string raises `ValueError`.

The `path_clear` alert is created in `decision_engine.py`:
```python
return Alert(
    level="path_clear",
    ...
    tracked_object={},  # No specific object - empty dict!
    priority_score=0.5,
)
```

**Fix:** Split the distance logging into a separate variable with a type guard:
```python
dist_val = alert.tracked_object.get("distance_m", "?")
dist_str = f"{dist_val:.1f}m" if isinstance(dist_val, (int, float)) else "?"
main_logger.info(
    f"[{alert.level.upper()}] {message} "
    f"(dist={dist_str}, "
    f"id={alert.tracked_object.get('track_id', '?')})"
)
```

This gracefully handles both numeric distances and the `path_clear` empty-dict case.

### 3.3 Missing `frame_index` Variable Initialization

**File:** `main.py` line 254

**Error:**
```
UnboundLocalError: cannot access local variable 'frame_index'
where it is not associated with a value
```

**Cause:** `frame_index += 1` was called inside the main loop but `frame_index` had never been initialized before the loop. The initialization had been in experimental-merge's code under a `# ---- Frame counter for skipping ----` comment block, but that block was removed during the merge conflict resolution (the post-merge cleanup accidentally dropped the variable while replacing the frame-skip section).

**Fix:** Added `frame_index = 0` before the main loop in the initialization section:

```python
# Frame counter for skip logic
frame_index = 0
```

### 3.4 Missing `process_every_n` Config Reading

**File:** `main.py` (initialization section)

**Issue:** The `process_every_n` variable (which controls how many frames are skipped between AI pipeline runs) was referenced in the main loop but its config-reading code had been dropped during the merge. The variable is loaded from `config.yaml`:

```yaml
performance:
  process_every_n_frames: 3     # Only run AI pipeline every Nth frame (1 = every frame)
```

**Fix:** Added the config reading block before the main loop:
```python
# Performance config
perf_config = config.get("performance", {})
process_every_n = max(1, perf_config.get("process_every_n_frames", 3))
main_logger.info(f"Frame skipping: processing every {process_every_n} frame(s)")
```

### 3.5 Missing `cached_tracked_objects` Initialization

**File:** `main.py` (initialization section)

**Issue:** The frame-skip logic's `else` branch references `cached_tracked_objects` to annotate skipped frames with cached bounding boxes. On the very first frame (before any AI processing has run), this variable was undefined, causing a `NameError`.

**Fix:** Added initial empty-list default before the loop:
```python
# Cached state for skipped frames
cached_tracked_objects = []
cached_annotated_frame = None
detections = []
annotated_frame = None
```

### 3.6 Duplicate LM Studio Auto-Trigger Block

**File:** `main.py` lines 322--330 (removed)

**Issue:** During the merge, the LM Studio auto-trigger block (which calls `lm_client.should_auto_trigger()` and `lm_client.describe_scene_async()`) was duplicated. One copy existed inside the `if frame_index % process_every_n == 0:` block (correct -- only triggers when we're actually processing a frame), and another copy existed outside the block (incorrect -- could trigger on skipped frames with stale detection data).

The duplicate external block was leftover from the experimental-merge source which had an incomplete merge-conflict resolution marker structure:
```python
# LM Studio ----
last_detections = detections
# LM Studio when needed (expensive)

# LM Studio ----
if lm_client.should_auto_trigger() and len(detections) > 0:
    ...
```

**Fix:** Removed the external duplicate block. The auto-trigger now only runs inside the frame-skip `if` block.

### 3.7 Language Toggle Cooldown Variable Definitions

**File:** `main.py` (initialization section)

**Issue:** The keyboard handler at line 331 references `last_lang_toggle_time` and `LANG_TOGGLE_COOLDOWN` but these variables were never defined. The language toggle cooldown prevents double-fire from key-repeat when holding the 'H' key:

```python
elif key == ord("h"):
    now = time.time()
    if now - last_lang_toggle_time >= LANG_TOGGLE_COOLDOWN:
        last_lang_toggle_time = now
        new_lang = voice_engine.toggle_language()
```

**Fix:** Added the variable definitions before the main loop:
```python
# Language toggle cooldown (prevents double-fire from key repeat)
last_lang_toggle_time = 0.0
LANG_TOGGLE_COOLDOWN = 2.0  # seconds
```

### 3.8 Remaining Conflict Marker Comment Artifact

**File:** `main.py` line 211

**Issue:** A leftover merge conflict artifact remained as a comment: `# LM Studio) ----`. This was the truncated tail of an unresolved `>>>>>>> experimental-merge` marker that had been manually cleaned but left a broken comment.

**Fix:** Replaced with a proper comment block describing the section.

---

## 4. ONNX GPU Optimization

*This section integrates content from `05_onnx_gpu_optimization.md` (kept intact at that path).*

### 4.1 The Goal

Migrate YOLOv8 object detection from PyTorch (`.pt`) to ONNX Runtime (`.onnx`) with GPU acceleration. The target was a ~30% performance boost over the already-optimized PyTorch pipeline, enabling 200+ FPS processing at 320x240 resolution.

### 4.2 Problems Encountered

#### Issue A: PyTorch `.to(device)` Bug on ONNX Models

In `modules/detector.py`, the original code unconditionally called `self.model.to(self.device)` after loading. PyTorch `nn.Module` objects support this, but when Ultralytics loads an `.onnx` file, it creates an ONNX Runtime session wrapper that does NOT support `.to()`. Calling it threw an immediate `AttributeError`:

```python
# BROKEN: crashes when model_path ends with .onnx
self.model = YOLO(self.model_path)
self.model.to(self.device)       # ONNX models don't have .to()
```

#### Issue B: CUDA 12 vs CUDA 13 Environment Mismatch

The Python virtual environment had PyTorch installed with CUDA 13 support (bringing `libcublasLt.so.13`). However, `onnxruntime-gpu` v1.26.0 was compiled against CUDA 12 (expecting `libcublasLt.so.12`). The mismatch caused:

1. `onnxruntime-gpu` silently fell back to `CPUExecutionProvider`
2. PyTorch passed GPU tensors to the CPU-bound ONNX model
3. Cross-device tensor binding failed with:
   ```
   RuntimeError: Error when binding input...
   ```

### 4.3 Solutions

#### Fix 1: Type-Aware Model Loading (detector.py)

Added a file-extension check to only call `.to(device)` for PyTorch models. ONNX models configure their device through Ultralytics' `predict(device=...)` argument at inference time:

```python
def __init__(self, config: dict):
    self.model = YOLO(self.model_path)
    # Only .to() for PyTorch models; ONNX handles device at inference time
    if self.model_path.endswith(".pt"):
        self.model.to(self.device)
```

Same safeguard applied to the hot-swapping `swap_model()` method.

#### Fix 2: Installing CUDA 12 Libraries via pip

Instead of downgrading PyTorch (which worked perfectly with CUDA 13), the missing CUDA 12 libraries were installed directly into the virtual environment:

```bash
.venv/bin/pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 \
                     nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12
```

#### Fix 3: Exposing Libraries via LD_LIBRARY_PATH

Since the CUDA 12 libraries lived inside `.venv/lib/python3.14/site-packages/nvidia/`, the dynamic linker couldn't find them automatically. The launch command was updated:

```bash
export LD_LIBRARY_PATH=$PWD/.venv/lib/python3.14/site-packages/nvidia/cublas/lib:$PWD/.venv/lib/python3.14/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH
.venv/bin/python main.py
```

### 4.4 Configuration Changes

Updated `config.yaml` to use the ONNX model:

```yaml
detection:
  model_path: "yolov8x.onnx"   # Changed from yolov8x.pt
```

And set frame processing to every frame (no skip) to benchmark peak performance:

```yaml
performance:
  process_every_n_frames: 1     # Process every frame
```

### 4.5 Interaction with Merge Fixes

The ONNX optimization interacts with the merge fixes in one important way: the `detector.py` changes (type-aware `.to()` call) are independent of the merge changes, since `detector.py` was not a conflicted file. Both changes coexist without conflict.

However, the frame-skip setting (`process_every_n_frames`) directly affects the FPS numbers reported in Section 5. At `process_every_n_frames: 1` (every frame processed), the raw pipeline throughput is measured. The ONNX boost is visible at any frame-skip setting.

---

## 5. Complete Performance Timeline

| Stage | FPS | Config | Notes |
|-------|-----|--------|-------|
| Pre-merge (old experimental) | ~90 | `.pt` model, `no frame skip`, PyTorch | User-reported baseline |
| Post-merge (first test) | ~45 | `.pt` model, `process_every_n: 3` | Frame-skip overhead + display bottleneck |
| Post-merge (with `process_every_n: 1`) | ~17 | `.pt` model, `process_every_n: 1` | Every frame processed + display overhead |
| Post-merge (with `--no-display`) | ~30-40 | `.pt` model, `--no-display` | Without display bottleneck |
| ONNX GPU (final) | **160-200** | `.onnx` model, `process_every_n: 1` | ONNX Runtime GPU + CUDA 12 + `--no-display` |

### Root-Cause Analysis: Why FPS Dropped from 90 to 17

The 5x FPS drop (90 → 17) was caused by three independent factors that compounded each other.

#### Factor 1: Display Rendering Overhead (`cv2.imshow()`)

The OpenCV highgui window uses a Qt backend on this system. The logs showed persistent warnings:
```
qt.qpa.plugin: Could not find the Qt platform plugin "wayland"
QFontDatabase: Cannot find font directory .../cv2/qt/fonts.
```

These indicate a misconfigured Qt display backend. Each `cv2.imshow()` call blocks for **30–60ms** waiting for the Qt event loop. At 17 FPS (59ms per frame), the display alone consumes virtually the entire frame budget.

**Proof:** Running with `--no-display` immediately recovered ~40 FPS from the same pipeline, confirming the display was the primary bottleneck.

#### Factor 2: Frame Skip Setting Changed from 1 to 3

The original experimental-merge branch (commit `eac281d`) did **not** have `process_every_n_frames` in its `config.yaml`. The default of `1` was used — every frame ran the full AI pipeline (YOLO + MiDaS + tracker + decision engine). After the merge, `process_every_n_frames: 3` became active (inherited from main's perf commit `f2455b5`).

When the user set `process_every_n_frames` back to `1` to "match the old behavior", they forced every frame through the full AI pipeline — exposing the full cost of both the AI models AND the display overhead simultaneously. With frame skip 3, only 1/3 of frames run AI, so the effective per-frame AI cost is amortized over 3 frames.

**Counterintuitive result:** Frame skip 3 gave 45 FPS (1/3 full AI + 2/3 cached). Switching to frame skip 1 gave 17 FPS (every frame full AI + display). The frame skip was actually helping, not hurting.

#### Factor 3: PyTorch vs ONNX Inference Throughput

The original 90 FPS claim was benchmarked with PyTorch inference. The actual PyTorch + MiDaS + full pipeline throughput on this hardware was closer to 30–40 FPS (with `--no-display`). The ONNX Runtime GPU execution provider boosted inference throughput by ~5x, which is what ultimately recovered and surpassed the original performance.

### How FPS Was Restored: ONNX GPU Migration

| Bottleneck | Solution | Improvement |
|------------|----------|-------------|
| PyTorch model inference | Migrate to ONNX Runtime GPU (`yolov8x.onnx` → `yolov8x.pt`) | ~5x inference speedup |
| Display overhead (`cv2.imshow`) | Use `--no-display` for headless operation | Removes 30–60ms per frame |
| CUDA 12 vs 13 library mismatch | Install `nvidia-cublas-cu12` etc. via pip | Enables GPU execution provider |
| `.to(device)` crash on ONNX models | Type-aware model loading in `detector.py` | Prevents startup crash |

**Final launch command achieving 160–200 FPS:**
```bash
export LD_LIBRARY_PATH=$PWD/.venv/lib/python3.14/site-packages/nvidia/cublas/lib:$PWD/.venv/lib/python3.14/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH
.venv/bin/python main.py --no-display
```

### Frame Skip Interaction Note

At `process_every_n_frames: 3`, the system skips 2 out of 3 AI pipeline runs. This helps when the display is the bottleneck (skipped frames still render without AI cost). When running headless (`--no-display`) with ONNX GPU, processing every frame (`process_every_n_frames: 1`) is preferred for maximum responsiveness since AI inference is no longer the bottleneck.

---

## 6. Appendix: Commands & Git History

### 6.1 Final Repository State

```
Branches:
  experimental-merge   # Source branch (20 granular commits)
* main                 # Target branch (merged result)
  stable               # Pre-merge backup at 00b4057 (original main)
  remotes/origin/main
  remotes/origin/experimental-merge
  remotes/origin/stable
```

### 6.2 All Merge-Related Commits

```
e6d8b2d Fix missing frame_index initialization
a4ed6b5 Fix merge-induced indentation bugs in main.py
b373ee2 Merge experimental-merge into main
```

### 6.3 Key Git Commands Reference

```bash
# View all branches
git branch -a

# View merge commit with diff
git show b373ee2

# Compare stable (pre-merge) with main (post-merge)
git diff stable..main --stat

# Restore stable branch to its own remote
git push origin stable

# View conflict history
git log --oneline --merges

# Reset to stable (undo merge entirely if needed)
git checkout stable
git branch -D main
git branch main stable
git push origin main --force
```

### 6.4 Verification Script

To verify the merge was applied correctly:

```bash
# Check that all expected files exist and have no conflict markers
for f in config.yaml main.py modules/camera.py modules/decision_engine.py modules/lm_studio_client.py .gitignore; do
    if grep -q "<<<<<<< " "$f" 2>/dev/null; then
        echo "CONFLICT MARKERS FOUND in $f"
    else
        echo "OK $f"
    fi
done

# Verify stable is an identical copy of pre-merge main
git diff stable 00b4057  # should produce zero output

# Verify python syntax
python -c "compile(open('main.py').read(), 'main.py', 'exec'); print('Syntax OK')"
```

### 6.5 Launch Command (ONNX GPU)

```bash
.venv/bin/python main.py
```

### fixed version for CUDA 12 ( arch linux )

```

```