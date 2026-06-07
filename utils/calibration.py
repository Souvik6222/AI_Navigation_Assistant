# ============================================================
# utils/calibration.py — MiDaS depth-to-meters calibration
# ============================================================

import numpy as np
from utils.logger import get_logger

log = get_logger("calibration")


class DepthCalibrator:
    """
    Maps MiDaS relative depth values to approximate real-world distances in meters.

    MiDaS outputs relative (inverse) depth — higher values = closer to camera.
    We use an inverse mapping:  distance_m = scale / (depth_value + offset)

    The scale and offset are tunable calibration parameters. For best results,
    calibrate against a known distance (e.g., hold an object at 1m and adjust).
    """

    def __init__(self, config: dict):
        """
        Args:
            config: depth.calibration section from config.yaml containing:
                scale, offset, min_distance, max_distance
        """
        cal = config.get("depth", {}).get("calibration", {})
        self.scale = cal.get("scale", 3.0)
        self.offset = cal.get("offset", 0.5)
        self.min_distance = cal.get("min_distance", 0.3)
        self.max_distance = cal.get("max_distance", 5.0)

        log.debug(
            f"Calibration initialized: scale={self.scale}, offset={self.offset}, "
            f"range=[{self.min_distance}–{self.max_distance}]m"
        )

    def calibrate(self, depth_value: float) -> float:
        """
        Convert a single MiDaS depth value to approximate meters.

        Args:
            depth_value: Normalized depth value (0.0–1.0) from MiDaS.
                         Higher = closer to camera.

        Returns:
            Estimated distance in meters, clamped to [min_distance, max_distance].
        """
        if depth_value <= 0.001:
            return self.max_distance

        distance = self.scale / (depth_value + self.offset)
        return float(np.clip(distance, self.min_distance, self.max_distance))

    def calibrate_region(self, depth_map: np.ndarray, bbox: tuple) -> float:
        """
        Sample depth at the center region of a bounding box and convert to meters.

        Uses a small central patch (middle 20% of bbox) for robustness against
        edge artifacts.

        Args:
            depth_map: Full normalized depth map from MiDaS (H×W float array).
            bbox: Bounding box as (x1, y1, x2, y2).

        Returns:
            Estimated distance in meters.
        """
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = depth_map.shape[:2]

        # Clamp to frame bounds
        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        if x2 <= x1 or y2 <= y1:
            return self.max_distance

        # Sample central 20% region for stability
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        bw = x2 - x1
        bh = y2 - y1
        margin_x = max(1, int(bw * 0.1))
        margin_y = max(1, int(bh * 0.1))

        region = depth_map[
            max(0, cy - margin_y): min(h, cy + margin_y),
            max(0, cx - margin_x): min(w, cx + margin_x),
        ]

        if region.size == 0:
            # Fallback: single center pixel
            depth_value = float(depth_map[cy, cx])
        else:
            # Use median for robustness against outliers
            depth_value = float(np.median(region))

        return self.calibrate(depth_value)
