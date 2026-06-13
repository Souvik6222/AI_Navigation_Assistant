# ============================================================
# modules/depth_estimator.py — MiDaS monocular depth estimation
# ============================================================
#
# Anti-hallucination improvement: uses rolling percentile-based
# normalisation instead of per-frame min/max. This prevents a
# single object in frame from always mapping to depth≈1.0 (which
# would give a false ~1.67m regardless of actual distance).
# ============================================================

import cv2
import numpy as np
import torch
from collections import deque
from utils.logger import get_logger
from utils.calibration import DepthCalibrator

log = get_logger("depth")

# Number of recent frames to track for global reference range
_REFERENCE_WINDOW = 30


class DepthEstimator:
    """
    MiDaS wrapper for monocular depth estimation.

    Loads MiDaS v2.1 Small via torch.hub for fast CPU inference (20–40ms).
    Outputs a normalized depth map and converts to approximate meters
    using the DepthCalibrator.

    Includes temporal smoothing to reduce frame-to-frame depth flicker.

    Normalisation uses a rolling global reference range (5th/95th percentile)
    instead of per-frame min/max, so that depth values are stable even when
    only a single object is visible.
    """

    def __init__(self, config: dict):
        """
        Initialize MiDaS model and depth calibrator.

        Args:
            config: Full config dict. Uses 'depth' section.
        """
        depth_config = config.get("depth", {})
        self.model_type = depth_config.get("model_type", "MiDaS_small")
        self.smoothing_frames = depth_config.get("temporal_smoothing_frames", 3)

        # Initialize calibrator
        self.calibrator = DepthCalibrator(config)

        # Temporal smoothing buffer: stores last N normalised depth maps
        self._depth_buffer: deque[np.ndarray] = deque(maxlen=self.smoothing_frames)

        # Rolling reference range: stores (p5, p95) from recent raw depth maps
        # so normalisation is stable across frames instead of resetting per-frame.
        self._ref_history: deque[tuple[float, float]] = deque(maxlen=_REFERENCE_WINDOW)
        self._global_ref_min: float | None = None
        self._global_ref_max: float | None = None

        # Load MiDaS model
        log.info(f"Loading MiDaS model: {self.model_type}")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Monkey-patch torch.hub validation to prevent GitHub API rate-limit
        # crashes (HTTP 403) and KeyError: 'Authorization' bug.
        # MiDaS internally calls torch.hub.load for its EfficientNet backbone,
        # which triggers this validation. Safe to skip for known repos.
        _original_validate = torch.hub._validate_not_a_forked_repo
        torch.hub._validate_not_a_forked_repo = lambda *args, **kwargs: None

        try:
            self.model = torch.hub.load(
                "intel-isl/MiDaS",
                self.model_type,
                trust_repo=True,
                skip_validation=True,
            )
            self.model.to(self.device)
            self.model.eval()

            # Load appropriate transform
            midas_transforms = torch.hub.load(
                "intel-isl/MiDaS",
                "transforms",
                trust_repo=True,
                skip_validation=True,
            )
        finally:
            # Restore original validation
            torch.hub._validate_not_a_forked_repo = _original_validate

        if self.model_type == "MiDaS_small":
            self.transform = midas_transforms.small_transform
        elif self.model_type == "DPT_Hybrid":
            self.transform = midas_transforms.dpt_transform
        else:
            self.transform = midas_transforms.dpt_transform

        log.info(f"MiDaS ready on {self.device} — temporal smoothing: {self.smoothing_frames} frames")

    def _update_reference_range(self, raw_depth: np.ndarray) -> None:
        """
        Update the rolling global reference range from a raw (unnormalised)
        MiDaS depth map.

        Uses 5th and 95th percentiles so outliers don't skew the range.
        The global reference is an exponentially weighted moving average
        of recent per-frame percentiles for smooth transitions.
        """
        p5 = float(np.percentile(raw_depth, 5))
        p95 = float(np.percentile(raw_depth, 95))

        # Protect against degenerate frames where the range is tiny
        if p95 - p5 < 1e-3:
            # If the frame is nearly uniform, widen the range slightly
            mid = (p5 + p95) / 2.0
            p5 = mid - 0.5
            p95 = mid + 0.5

        self._ref_history.append((p5, p95))

        # Compute global reference as median of recent per-frame percentiles.
        # Median is robust to sudden outlier frames.
        all_p5 = [h[0] for h in self._ref_history]
        all_p95 = [h[1] for h in self._ref_history]
        self._global_ref_min = float(np.median(all_p5))
        self._global_ref_max = float(np.median(all_p95))

    def _normalise_depth(self, raw_depth: np.ndarray) -> np.ndarray:
        """
        Normalise a raw MiDaS depth map to 0–1 using the rolling global
        reference range instead of per-frame min/max.

        If the global reference hasn't stabilised yet (first few frames),
        falls back to per-frame normalisation with a wider margin.

        Returns:
            Normalised depth map (float32, values clipped to 0.0–1.0).
            Higher values = closer to camera.
        """
        self._update_reference_range(raw_depth)

        ref_min = self._global_ref_min
        ref_max = self._global_ref_max

        if ref_min is None or ref_max is None or (ref_max - ref_min) < 1e-6:
            # Fallback for first frame(s): use per-frame range
            d_min = raw_depth.min()
            d_max = raw_depth.max()
            if d_max - d_min > 0:
                return ((raw_depth - d_min) / (d_max - d_min)).astype(np.float32)
            return np.zeros_like(raw_depth, dtype=np.float32)

        normalised = (raw_depth - ref_min) / (ref_max - ref_min)
        # Clip to [0, 1] — values outside the reference range are clamped
        return np.clip(normalised, 0.0, 1.0).astype(np.float32)

    @torch.no_grad()
    def estimate(self, frame: np.ndarray) -> np.ndarray:
        """
        Compute a normalized depth map from a BGR frame.

        Args:
            frame: Input BGR frame (numpy array, H×W×3).

        Returns:
            Normalized depth map (H×W float32 array, values 0.0–1.0).
            Higher values = closer to camera.
        """
        # Convert BGR to RGB for MiDaS
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Apply MiDaS transform
        input_batch = self.transform(rgb_frame).to(self.device)

        # Run inference
        prediction = self.model(input_batch)

        # Resize to original frame dimensions
        prediction = torch.nn.functional.interpolate(
            prediction.unsqueeze(1),
            size=frame.shape[:2],
            mode="bicubic",
            align_corners=False,
        ).squeeze()

        raw_depth = prediction.cpu().numpy()

        # Normalise using rolling global reference range (anti-hallucination)
        depth_map = self._normalise_depth(raw_depth)

        # Add to temporal buffer
        self._depth_buffer.append(depth_map)

        # Apply temporal smoothing (running average)
        if len(self._depth_buffer) > 1:
            smoothed = np.mean(np.stack(self._depth_buffer), axis=0)
            return smoothed.astype(np.float32)

        return depth_map

    def get_distance(self, depth_map: np.ndarray, bbox: tuple) -> float:
        """
        Get the estimated distance in meters for an object defined by its bounding box.

        Samples the central region of the bounding box from the depth map
        and converts to meters using the calibrator.

        Args:
            depth_map: Normalized depth map from estimate().
            bbox: Bounding box as (x1, y1, x2, y2).

        Returns:
            Estimated distance in meters.
        """
        return self.calibrator.calibrate_region(depth_map, bbox)
