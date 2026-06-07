# ============================================================
# utils/frame_utils.py — Frame processing, annotation, encoding
# ============================================================

import base64
import cv2
import numpy as np


def resize_frame(frame: np.ndarray, width: int = 640, height: int = 480) -> np.ndarray:
    """
    Resize a frame to the target dimensions.

    Args:
        frame: Input BGR frame from OpenCV.
        width: Target width in pixels.
        height: Target height in pixels.

    Returns:
        Resized frame.
    """
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)


def annotate_frame(
    frame: np.ndarray,
    tracked_objects: list,
    colors: dict | None = None,
) -> np.ndarray:
    """
    Draw bounding boxes, labels, distances, and directions on the frame.

    Color-coded by alert level:
        - URGENT (red): distance < 0.8m
        - WARNING (orange): 0.8–1.5m
        - INFO (green): 1.5–2.5m

    Args:
        frame: Input BGR frame.
        tracked_objects: List of tracked object dicts with keys:
            label, confidence, bbox (x1,y1,x2,y2), distance_m, direction, track_id, alert_level
        colors: Optional dict with keys 'urgent', 'warning', 'info' mapping to BGR tuples.

    Returns:
        Annotated frame (copy).
    """
    annotated = frame.copy()
    h, w = annotated.shape[:2]

    if colors is None:
        colors = {
            "urgent": (0, 0, 255),      # Red
            "warning": (0, 165, 255),    # Orange
            "info": (0, 255, 0),         # Green
            "silent": (180, 180, 180),   # Gray
        }

    # Draw zone divider lines (subtle)
    zone_1 = int(w * 0.33)
    zone_2 = int(w * 0.66)
    cv2.line(annotated, (zone_1, 0), (zone_1, h), (80, 80, 80), 1, cv2.LINE_AA)
    cv2.line(annotated, (zone_2, 0), (zone_2, h), (80, 80, 80), 1, cv2.LINE_AA)

    # Draw zone labels at top
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(annotated, "LEFT", (10, 20), font, 0.5, (120, 120, 120), 1, cv2.LINE_AA)
    cv2.putText(annotated, "CENTER", (zone_1 + 10, 20), font, 0.5, (120, 120, 120), 1, cv2.LINE_AA)
    cv2.putText(annotated, "RIGHT", (zone_2 + 10, 20), font, 0.5, (120, 120, 120), 1, cv2.LINE_AA)

    for obj in tracked_objects:
        x1, y1, x2, y2 = obj.get("bbox", (0, 0, 0, 0))
        label = obj.get("label", "unknown")
        confidence = obj.get("confidence", 0.0)
        distance = obj.get("distance_m", -1.0)
        direction = obj.get("direction", "?")
        track_id = obj.get("track_id", -1)
        alert_level = obj.get("alert_level", "silent").lower()

        # Pick color based on alert level
        color = colors.get(alert_level, colors["silent"])

        # Draw bounding box
        thickness = 3 if alert_level == "urgent" else 2
        cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness)

        # Build label text
        dist_str = f"{distance:.1f}m" if distance >= 0 else "?"
        text_top = f"ID:{track_id} {label} {confidence:.0%}"
        text_bottom = f"{dist_str} {direction}"

        # Draw background rectangle for text readability
        (tw1, th1), _ = cv2.getTextSize(text_top, font, 0.45, 1)
        (tw2, th2), _ = cv2.getTextSize(text_bottom, font, 0.45, 1)
        max_tw = max(tw1, tw2)

        text_y = max(int(y1) - 8, 30)
        cv2.rectangle(
            annotated,
            (int(x1), text_y - th1 - th2 - 12),
            (int(x1) + max_tw + 6, text_y + 4),
            color,
            -1,
        )

        # Draw text (white on colored background)
        cv2.putText(annotated, text_top, (int(x1) + 3, text_y - th2 - 6), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(annotated, text_bottom, (int(x1) + 3, text_y), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # Draw danger pulse for URGENT objects (filled semi-transparent overlay)
        if alert_level == "urgent":
            overlay = annotated.copy()
            cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.15, annotated, 0.85, 0, annotated)

    return annotated


def draw_status_bar(
    frame: np.ndarray,
    language: str,
    fps: float,
    num_objects: int,
    groq_status: str = "",
) -> np.ndarray:
    """
    Draw a status bar at the bottom of the frame.

    Args:
        frame: Input BGR frame.
        language: Current language ("en" or "hi").
        fps: Current frames per second.
        num_objects: Number of currently tracked objects.
        groq_status: Optional Groq API status text.

    Returns:
        Frame with status bar.
    """
    h, w = frame.shape[:2]
    bar_height = 30

    # Draw dark background bar
    cv2.rectangle(frame, (0, h - bar_height), (w, h), (30, 30, 30), -1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    lang_label = "EN" if language == "en" else "HI"

    # Status text
    status_text = f"Lang: {lang_label} | FPS: {fps:.0f} | Objects: {num_objects}"
    if groq_status:
        status_text += f" | Groq: {groq_status}"

    status_text += " | [H] Toggle Lang | [D] Describe | [Q] Quit"

    cv2.putText(frame, status_text, (10, h - 10), font, 0.4, (200, 200, 200), 1, cv2.LINE_AA)

    return frame


def frame_to_base64(frame: np.ndarray) -> str:
    """
    Encode a BGR frame as a base64 JPEG string for Claude API.

    Args:
        frame: Input BGR frame.

    Returns:
        Base64-encoded JPEG string.
    """
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")
