# ============================================================
# modules/depth_estimator.py — MiDaS monocular depth estimation
# ============================================================

import cv2
import numpy as np
import torch
from collections import deque
from utils.logger import get_logger
from utils.calibration import DepthCalibrator

log = get_logger("depth")


class DepthEstimator:
    """
    MiDaS wrapper for monocular depth estimation.

    Loads MiDaS v2.1 Small via torch.hub for fast CPU inference (20–40ms).
    Outputs a normalized depth map and converts to approximate meters
    using the DepthCalibrator.

    Includes temporal smoothing to reduce frame-to-frame depth flicker.
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

        # Temporal smoothing buffer: stores last N depth maps
        self._depth_buffer: deque[np.ndarray] = deque(maxlen=self.smoothing_frames)

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

        depth_map = prediction.cpu().numpy()

        # Normalize to 0–1 range
        depth_min = depth_map.min()
        depth_max = depth_map.max()
        if depth_max - depth_min > 0:
            depth_map = (depth_map - depth_min) / (depth_max - depth_min)
        else:
            depth_map = np.zeros_like(depth_map)

        # Add to temporal buffer
        self._depth_buffer.append(depth_map)

        # Apply temporal smoothing (running average)
        if len(self._depth_buffer) > 1:
            smoothed = np.mean(np.stack(self._depth_buffer), axis=0)
            return smoothed.astype(np.float32)

        return depth_map.astype(np.float32)

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
