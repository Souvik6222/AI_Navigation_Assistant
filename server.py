# ============================================================
# server.py — FastAPI WebSocket Dashboard Server
# ============================================================
#
# Runs the same AI Navigation pipeline as main.py but streams
# frames, telemetry, and alerts to connected web dashboards
# via WebSocket.
#
# Usage:
#   python server.py
#   python server.py --port 8765
#
# Dashboard:
#   Open http://localhost:8765 in your browser
#
# ============================================================

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import time
import threading
import tempfile

import cv2
import numpy as np
import yaml
import torch

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from utils.logger import get_logger, setup_file_logging
from utils.frame_utils import resize_frame, annotate_frame, draw_status_bar, frame_to_base64
from modules.detector import ObjectDetector
from modules.depth_estimator import DepthEstimator
from modules.tracker import ObjectTracker
from modules.direction import get_direction
from modules.decision_engine import DecisionEngine
from modules.voice import VoiceEngine
from modules.claude_client import ClaudeClient

log = get_logger("server")

# ============================================================
# Globals (shared between pipeline thread and WebSocket tasks)
# ============================================================

# Latest data for broadcasting
latest_frame_b64 = ""
latest_telemetry = {}
alert_queue = asyncio.Queue()

# Connected WebSocket clients
connected_clients: set[WebSocket] = set()
clients_lock = threading.Lock()

# Pipeline control flags (modified by dashboard controls)
pipeline_controls = {
    "mute_all": False,
    "show_display": True,
}

# Module references (populated at startup)
modules = {}

# ---- Testing Mode globals ----
test_mode_state = {
    "active": False,             # True when processing an uploaded video
    "video_path": None,          # Path to the uploaded test video file
    "switch_requested": False,   # Flag to tell pipeline to swap source
    "stop_requested": False,     # Flag to tell pipeline to go back to camera
    "progress": 0.0,             # 0.0 – 1.0 progress through the video
    "total_frames": 0,
    "current_frame": 0,
    "video_fps": 0,              # Original FPS of the uploaded video
    "filename": "",              # Original filename for display
}

# Directory for uploaded test videos
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================
# Config Loader
# ============================================================

def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    if not os.path.exists(config_path):
        log.warning(f"Config file not found: {config_path} — using defaults")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    log.info(f"Configuration loaded from {config_path}")
    return config


# ============================================================
# Pipeline Thread
# ============================================================

def pipeline_thread(config: dict, loop: asyncio.AbstractEventLoop):
    """
    Main vision pipeline — runs in a dedicated thread.

    Captures frames, runs YOLO + MiDaS + tracking + decisions,
    and pushes results to global buffers for WebSocket broadcast.
    """
    global latest_frame_b64, latest_telemetry

    log.info("=" * 60)
    log.info("  AI Navigation Assistant — Server Mode")
    log.info("=" * 60)

    # ---- Initialize modules ----
    log.info("Initializing modules...")

    detector = ObjectDetector(config)
    depth_estimator = DepthEstimator(config)
    tracker = ObjectTracker(config)
    decision_engine = DecisionEngine(config)
    decision_engine.set_tracker(tracker)
    voice_engine = VoiceEngine(config)
    voice_engine.start()
    claude_client = ClaudeClient(config)
    claude_client.set_voice_engine(voice_engine)

    # Store module references for dashboard control
    modules["detector"] = detector
    modules["depth_estimator"] = depth_estimator
    modules["tracker"] = tracker
    modules["decision_engine"] = decision_engine
    modules["voice_engine"] = voice_engine
    modules["claude_client"] = claude_client

    # Config values
    dir_config = config.get("direction", {})
    left_boundary = dir_config.get("left_boundary", 0.33)
    right_boundary = dir_config.get("right_boundary", 0.66)

    cam_config = config.get("camera", {})
    cam_index = cam_config.get("device_index", 0)
    frame_width = cam_config.get("frame_width", 640)
    frame_height = cam_config.get("frame_height", 480)

    display_config = config.get("display", {})
    window_name = display_config.get("window_name", "AI Navigation Assistant")

    # Performance config
    perf_config = config.get("performance", {})
    process_every_n = max(1, perf_config.get("process_every_n_frames", 3))
    log.info(f"Frame skipping: processing every {process_every_n} frame(s)")

    # ---- Open webcam ----
    log.info(f"Opening camera (index={cam_index})...")
    cap = cv2.VideoCapture(cam_index)

    if not cap.isOpened():
        log.error("Failed to open webcam!")
        voice_engine.speak("Camera not found. Please check your webcam connection.", "en")
        # Don't return — allow test mode to work without a camera
        cap = None
    else:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        log.info(f"Camera opened — {frame_width}x{frame_height}")

    # Initial environment scan state
    initial_scan_triggered = False
    initial_scan_start_time = 0.0

    # FPS tracking
    fps_counter = 0
    fps_start_time = time.time()
    current_fps = 0.0

    # Telemetry throttle (send every 500ms)
    last_telemetry_time = 0.0

    # Test mode capture (separate from webcam cap)
    test_cap = None
    is_test_mode = False

    # Cached states for frame skipping
    frame_index = 0
    cached_tracked_objects = []
    lat_yolo = 0.0
    lat_midas = 0.0
    lat_tracking = 0.0
    detections = []
    tracked_objects = []

    log.info("Pipeline running in server mode — dashboard at http://localhost:8765")

    # Sync initial config to newly connected clients
    _push_config_sync(config, loop)

    # ============================================================
    # MAIN LOOP
    # ============================================================
    try:
        while True:
            loop_start = time.time()

            # ---- 0. Check for test mode switch ----
            if test_mode_state["switch_requested"]:
                test_mode_state["switch_requested"] = False
                video_path = test_mode_state["video_path"]
                if video_path and os.path.exists(video_path):
                    log.info(f"TESTING MODE: Switching to video {video_path}")
                    test_cap = cv2.VideoCapture(video_path)
                    if test_cap.isOpened():
                        is_test_mode = True
                        test_mode_state["active"] = True
                        test_mode_state["total_frames"] = int(test_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        test_mode_state["video_fps"] = test_cap.get(cv2.CAP_PROP_FPS) or 30
                        test_mode_state["current_frame"] = 0
                        test_mode_state["progress"] = 0.0
                        
                        # Fetch frame count in background thread to prevent blocking startup
                        def _async_frame_count(cap_obj):
                            try:
                                count = int(cap_obj.get(cv2.CAP_PROP_FRAME_COUNT))
                                if count > 0:
                                    test_mode_state["total_frames"] = count
                            except Exception:
                                pass
                        
                        test_mode_state["total_frames"] = 1  # placeholder
                        threading.Thread(target=_async_frame_count, args=(test_cap,), daemon=True).start()
                        
                        # Reset tracker for fresh test
                        tracker.reset() if hasattr(tracker, 'reset') else None
                        log.info(f"Test video opened @ {test_mode_state['video_fps']} fps (fetching total frames asynchronously)")
                    else:
                        log.error(f"Failed to open test video: {video_path}")
                        test_cap = None
                        test_mode_state["active"] = False

            if test_mode_state["stop_requested"]:
                test_mode_state["stop_requested"] = False
                if test_cap:
                    test_cap.release()
                    test_cap = None
                is_test_mode = False
                test_mode_state["active"] = False
                test_mode_state["progress"] = 0.0
                test_mode_state["current_frame"] = 0
                log.info("TESTING MODE: Stopped, returning to live camera")

            # ---- 1. Capture frame ----
            if is_test_mode and test_cap:
                # To prevent lag on heavy/high-FPS videos, calculate how many frames to skip
                # based on the elapsed time of processing.
                fps_video = test_mode_state["video_fps"]
                current_frame = test_mode_state["current_frame"]
                total = test_mode_state["total_frames"]
                
                # Check how much real time has passed since loop started
                now = time.time()
                if hasattr(pipeline_thread, "last_frame_time"):
                    elapsed = now - pipeline_thread.last_frame_time
                    # Calculate how many frames we should advance
                    frames_to_skip = int(elapsed * fps_video)
                    if frames_to_skip > 1:
                        # Skip ahead in the video capture stream to catch up
                        target_frame = min(total - 1, current_frame + frames_to_skip)
                        test_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                
                pipeline_thread.last_frame_time = now

                ret, frame = test_cap.read()
                if not ret:
                    # Video finished — loop or stop
                    log.info("TESTING MODE: Video finished")
                    test_cap.release()
                    test_cap = None
                    is_test_mode = False
                    test_mode_state["active"] = False
                    test_mode_state["progress"] = 1.0
                    if hasattr(pipeline_thread, "last_frame_time"):
                        delattr(pipeline_thread, "last_frame_time")
                    time.sleep(0.01)
                    continue
                
                test_mode_state["current_frame"] = int(test_cap.get(cv2.CAP_PROP_POS_FRAMES))
                test_mode_state["progress"] = test_mode_state["current_frame"] / total if total > 0 else 0
            elif cap and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue
            else:
                # No camera and not in test mode — wait
                time.sleep(0.1)
                continue

            frame = resize_frame(frame, frame_width, frame_height)
            frame_index += 1
            language = voice_engine.get_language()

            # Trigger initial environment scan on the very first frame
            if not initial_scan_triggered:
                initial_scan_triggered = True
                initial_scan_start_time = time.time()
                log.info("STARTUP: Triggering initial environment scene description")
                voice_engine.speak("Scanning environment. Please stand still.", language)
                
                # Run detections on this first frame to feed to the LLM
                first_detections = detector.detect(frame)
                if len(first_detections) > 0:
                    depth_map = depth_estimator.estimate(frame)
                    for det in first_detections:
                        det["direction"] = get_direction(
                            det["center_x"], frame_width, left_boundary, right_boundary
                        )
                        det["distance_m"] = depth_estimator.get_distance(depth_map, det["bbox"])
                
                # Send the first frame to Groq Vision
                if claude_client.enabled:
                    frame_b64 = frame_to_base64(frame)
                    claude_client.describe_scene_async(frame_b64, first_detections, language)
                    claude_client.mark_triggered()

            # Only run AI pipeline on every Nth frame
            if frame_index % process_every_n == 0:
                # ---- 2. YOLOv8 Detection ----
                t_yolo = time.time()
                detections = detector.detect(frame)
                lat_yolo = (time.time() - t_yolo) * 1000

                # ---- 3. MiDaS Depth (CONDITIONAL: only if objects are detected) ----
                if len(detections) > 0:
                    t_midas = time.time()
                    depth_map = depth_estimator.estimate(frame)
                    lat_midas = (time.time() - t_midas) * 1000

                    # ---- 4. Enrich with direction + distance ----
                    for det in detections:
                        det["direction"] = get_direction(
                            det["center_x"], frame_width, left_boundary, right_boundary
                        )
                        det["distance_m"] = depth_estimator.get_distance(depth_map, det["bbox"])
                else:
                    lat_midas = 0.0

                # ---- 5. Tracking ----
                t_track = time.time()
                tracked_objects = tracker.update(detections, frame_width)
                lat_tracking = (time.time() - t_track) * 1000
                cached_tracked_objects = tracked_objects

                # ---- 6. Decision engine ----
                alerts = decision_engine.evaluate(tracked_objects)

                # ---- 7. Voice + alert broadcast ----
                language = voice_engine.get_language()
                speak_info = config.get("voice", {}).get("speak_info_alerts", False)
                # Silence real-time voice alerts for the first 5 seconds to let the environment scan finish speaking
                silence_voice = (time.time() - initial_scan_start_time) < 5.0
                
                for alert_obj in alerts:
                    message = alert_obj.get_message(language)

                    if not pipeline_controls.get("mute_all", False):
                        if not silence_voice:
                            if alert_obj.level != "info" or speak_info:
                                voice_engine.speak(message, language)

                    # Push to async alert queue
                    alert_data = {
                        "type": "alert",
                        "level": alert_obj.level,
                        "message": message,
                        "timestamp": time.strftime("%H:%M:%S"),
                        "object": {
                            "label": alert_obj.tracked_object.get("label", "?"),
                            "distance_m": round(alert_obj.tracked_object.get("distance_m", 0), 1),
                            "direction": alert_obj.tracked_object.get("direction", "?"),
                            "track_id": alert_obj.tracked_object.get("track_id", -1),
                        },
                    }
                    try:
                        loop.call_soon_threadsafe(alert_queue.put_nowait, alert_data)
                    except Exception:
                        pass
            else:
                # Skipped frame: reuse cached tracked objects
                tracked_objects = cached_tracked_objects

            # ---- 8. Annotate frame ----
            for obj in tracked_objects:
                if "alert_level" not in obj:
                    dist = obj.get("distance_m", 999)
                    if dist < 0.8:
                        obj["alert_level"] = "urgent"
                    elif dist < 1.5:
                        obj["alert_level"] = "warning"
                    elif dist < 2.5:
                        obj["alert_level"] = "info"
                    else:
                        obj["alert_level"] = "silent"

            annotated_frame = annotate_frame(frame, tracked_objects)

            # Status bar on annotated frame
            language = voice_engine.get_language()
            annotated_frame = draw_status_bar(
                annotated_frame,
                language=language,
                fps=current_fps,
                num_objects=len(tracked_objects),
                groq_status=claude_client.get_status(),
            )

            # ---- 9. Local display (optional) ----
            if pipeline_controls.get("show_display", True):
                cv2.imshow(window_name, annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    log.info("Quit from local window")
                    break
            else:
                cv2.waitKey(1)

            # ---- 10. Encode frame for dashboard ----
            _, jpg_buf = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            latest_frame_b64 = base64.b64encode(jpg_buf).decode("utf-8")

            # ---- 11. Total latency ----
            lat_total = (time.time() - loop_start) * 1000

            # ---- 12. Telemetry update (throttled to 2Hz) ----
            now = time.time()
            if now - last_telemetry_time >= 0.5:
                last_telemetry_time = now
                latest_telemetry = {
                    "type": "telemetry",
                    "fps": round(current_fps, 1),
                    "resolution": {"width": frame_width, "height": frame_height},
                    "latency": {
                        "yolo": round(lat_yolo, 1),
                        "midas": round(lat_midas, 1),
                        "tracking": round(lat_tracking, 1),
                        "total": round(lat_total, 1),
                    },
                    "hw": {
                        "cuda": torch.cuda.is_available(),
                        "device": str(depth_estimator.device),
                        "camera_index": cam_index,
                        "model": detector.model_path,
                    },
                    "objects": [
                        {
                            "label": o.get("label", "?"),
                            "distance_m": round(o.get("distance_m", 0), 1),
                            "direction": o.get("direction", "?"),
                            "track_id": o.get("track_id", -1),
                            "alert_level": o.get("alert_level", "silent"),
                        }
                        for o in tracked_objects
                    ],
                    "test_mode": {
                        "active": test_mode_state["active"],
                        "progress": round(test_mode_state["progress"], 3),
                        "current_frame": test_mode_state["current_frame"],
                        "total_frames": test_mode_state["total_frames"],
                        "filename": test_mode_state["filename"],
                    },
                }

            # ---- 13. Auto-trigger Groq ----
            if claude_client.should_auto_trigger() and len(detections) > 0:
                frame_b64 = frame_to_base64(annotated_frame)
                claude_client.describe_scene_async(frame_b64, detections, language)
                claude_client.mark_triggered()

            # ---- FPS calculation ----
            fps_counter += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                current_fps = fps_counter / elapsed
                fps_counter = 0
                fps_start_time = time.time()

            # ---- Pacing Delay (Prevents video from playing too fast on skipped/fast frames) ----
            loop_elapsed = time.time() - loop_start
            target_fps = test_mode_state["video_fps"] if is_test_mode else 30.0
            target_frame_time = 1.0 / target_fps if target_fps > 0 else 0.033
            if loop_elapsed < target_frame_time:
                time.sleep(target_frame_time - loop_elapsed)

    except KeyboardInterrupt:
        log.info("Pipeline interrupted")
    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
    finally:
        log.info("Pipeline shutting down...")
        if cap:
            cap.release()
        if test_cap:
            test_cap.release()
        cv2.destroyAllWindows()
        voice_engine.stop()
        log.info("Pipeline stopped.")


def _push_config_sync(config: dict, loop: asyncio.AbstractEventLoop):
    """Push initial config state so the dashboard shows correct slider positions."""
    voice_cfg = config.get("voice", {})
    det_cfg = config.get("detection", {})
    dec_cfg = config.get("decision", {})
    thresholds = dec_cfg.get("thresholds", {})
    groq_cfg = config.get("groq", {})
    display_cfg = config.get("display", {})

    sync_msg = {
        "type": "config_sync",
        "data": {
            "volume": int(voice_cfg.get("pyttsx3_volume", 1.0) * 100),
            "speech_rate": voice_cfg.get("pyttsx3_rate", 175),
            "language": voice_cfg.get("default_language", "en"),
            "confidence_threshold": det_cfg.get("confidence_threshold", 0.80),
            "urgent_threshold": thresholds.get("urgent", 0.8),
            "warning_threshold": thresholds.get("warning", 1.5),
            "model_path": det_cfg.get("model_path", "yolov8x.pt"),
            "groq_enabled": groq_cfg.get("enabled", True),
            "groq_interval": groq_cfg.get("auto_trigger_interval_seconds", 30),
            "show_display": display_cfg.get("show_window", True),
            "mute_all": False,
        },
    }
    # Store for new connections
    modules["_config_sync"] = sync_msg


# ============================================================
# Control Handler
# ============================================================

def apply_control(key: str, value):
    """Apply a control command from the dashboard to the running pipeline."""
    log.info(f"Dashboard control: {key} = {value}")

    # Update cache so any new connections get correct state
    sync_msg = modules.get("_config_sync")
    if sync_msg and "data" in sync_msg:
        sync_msg["data"][key] = value

    try:
        if key == "volume":
            v = int(value)
            vol = v / 100.0
            ve = modules.get("voice_engine")
            if ve:
                ve._volume = vol
                if ve._pyttsx3_engine:
                    ve._pyttsx3_engine.setProperty("volume", vol)

        elif key == "speech_rate":
            rate = int(value)
            ve = modules.get("voice_engine")
            if ve:
                ve._rate = rate
                if ve._pyttsx3_engine:
                    ve._pyttsx3_engine.setProperty("rate", rate)

        elif key == "language":
            ve = modules.get("voice_engine")
            if ve:
                ve._language = str(value)
                lang_name = "Hindi" if value == "hi" else "English"
                log.info(f"Language set to: {lang_name}")

        elif key == "confidence_threshold":
            det = modules.get("detector")
            if det:
                det.confidence_threshold = float(value)

        elif key == "urgent_threshold":
            de = modules.get("decision_engine")
            if de:
                de.urgent_threshold = float(value)

        elif key == "warning_threshold":
            de = modules.get("decision_engine")
            if de:
                de.warning_threshold = float(value)

        elif key == "model_path":
            det = modules.get("detector")
            if det:
                # Run in separate thread to avoid blocking
                threading.Thread(
                    target=det.swap_model,
                    args=(str(value),),
                    daemon=True,
                    name="ModelSwap",
                ).start()

        elif key == "groq_enabled":
            cc = modules.get("claude_client")
            if cc:
                cc.enabled = bool(value)

        elif key == "groq_interval":
            cc = modules.get("claude_client")
            if cc:
                cc.auto_interval = int(value)

        elif key == "show_display":
            pipeline_controls["show_display"] = bool(value)

        elif key == "mute_all":
            pipeline_controls["mute_all"] = bool(value)

        elif key == "replay_last":
            # Voice engine will replay via a spoken message
            ve = modules.get("voice_engine")
            if ve:
                ve.speak("Replaying last alert.", ve.get_language())

        elif key == "test_mode_stop":
            log.info("Dashboard: stop test mode requested")
            test_mode_state["stop_requested"] = True

    except Exception as e:
        log.error(f"Control error ({key}): {e}")


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(title="AI Navigation Assistant Dashboard")

# Dashboard directory paths
dashboard_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
assets_dir = os.path.join(dashboard_dir, "assets")


@app.get("/")
async def serve_dashboard():
    """Serve the React dashboard index.html."""
    return FileResponse(os.path.join(dashboard_dir, "index.html"))


@app.post("/api/upload-video")
def upload_video(file: UploadFile = File(...)):
    """
    Upload a test video to process through the AI pipeline.
    Saves the file to temp_uploads/ and signals the pipeline to switch.
    """
    # Validate file type
    allowed_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_exts:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unsupported format: {ext}. Use: {', '.join(allowed_exts)}"}
        )

    # Save file
    save_path = os.path.join(UPLOAD_DIR, f"test_video{ext}")
    try:
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        log.error(f"Failed to save uploaded video: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to save video"})
    finally:
        file.file.close()

    # Signal pipeline to switch to this video
    test_mode_state["video_path"] = save_path
    test_mode_state["filename"] = file.filename or "test_video"
    test_mode_state["switch_requested"] = True
    test_mode_state["stop_requested"] = False
    test_mode_state["progress"] = 0.0
    test_mode_state["current_frame"] = 0

    log.info(f"Test video uploaded: {file.filename} -> {save_path}")
    return JSONResponse(content={
        "status": "ok",
        "filename": file.filename,
        "path": save_path,
    })


@app.get("/api/test-mode/status")
async def test_mode_status():
    """Return current test mode state."""
    return JSONResponse(content={
        "active": test_mode_state["active"],
        "progress": round(test_mode_state["progress"], 3),
        "current_frame": test_mode_state["current_frame"],
        "total_frames": test_mode_state["total_frames"],
        "filename": test_mode_state["filename"],
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard communication."""
    await websocket.accept()
    connected_clients.add(websocket)
    log.info(f"Dashboard client connected ({len(connected_clients)} total)")

    # Send initial config sync
    sync_msg = modules.get("_config_sync")
    if sync_msg:
        try:
            await websocket.send_json(sync_msg)
        except Exception:
            pass

    # Two async tasks: send loop + receive loop
    send_task = asyncio.create_task(_ws_send_loop(websocket))
    receive_task = asyncio.create_task(_ws_receive_loop(websocket))

    try:
        # Wait for either to finish (disconnect)
        done, pending = await asyncio.wait(
            [send_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception:
        pass
    finally:
        connected_clients.discard(websocket)
        log.info(f"Dashboard client disconnected ({len(connected_clients)} total)")


async def _ws_send_loop(websocket: WebSocket):
    """Send frames, telemetry, and alerts to a connected dashboard client."""
    last_frame_sent = 0.0
    last_telem_sent = 0.0
    frame_interval = 1.0 / 30  # Max ~30 fps to dashboard

    try:
        while True:
            now = time.time()

            # Send frame
            if latest_frame_b64 and (now - last_frame_sent) >= frame_interval:
                await websocket.send_json({"type": "frame", "data": latest_frame_b64})
                last_frame_sent = now

            # Send telemetry (2Hz)
            if latest_telemetry and (now - last_telem_sent) >= 0.5:
                await websocket.send_json(latest_telemetry)
                last_telem_sent = now

            # Send any pending alerts
            while not alert_queue.empty():
                try:
                    alert = alert_queue.get_nowait()
                    await websocket.send_json(alert)
                except asyncio.QueueEmpty:
                    break

            await asyncio.sleep(0.03)  # ~33ms tick

    except (WebSocketDisconnect, Exception):
        pass


async def _ws_receive_loop(websocket: WebSocket):
    """Receive control commands from the dashboard."""
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "control":
                key = data.get("key", "")
                value = data.get("value")
                if key:
                    apply_control(key, value)
    except (WebSocketDisconnect, Exception):
        pass


# ---- Static file mounts (must be AFTER explicit routes) ----
# Mount /assets for React's hashed JS/CSS bundles
if os.path.isdir(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Mount /static for any other static files in the dashboard folder
app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")


# ============================================================
# Entry Point
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(description="AI Nav Assistant — Dashboard Server")
    parser.add_argument("--port", "-p", type=int, default=8765, help="Server port (default: 8765)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    # Get the asyncio event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start pipeline in a background thread
    pipeline = threading.Thread(
        target=pipeline_thread,
        args=(config, loop),
        daemon=True,
        name="PipelineThread",
    )
    pipeline.start()

    log.info(f"Starting dashboard server on http://localhost:{args.port}")
    log.info(f"Open http://localhost:{args.port} in your browser")

    # Run uvicorn on the event loop
    uvi_config = uvicorn.Config(
        app=app,
        host=args.host,
        port=args.port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(uvi_config)
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
