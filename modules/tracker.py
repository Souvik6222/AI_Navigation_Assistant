# ============================================================
# modules/tracker.py — ByteTrack object tracking integration
# ============================================================

import time
from collections import defaultdict
from utils.logger import get_logger

log = get_logger("tracker")


class ObjectTracker:
    """
    Object tracker using ByteTrack via Ultralytics.

    Assigns persistent track IDs to detected objects across frames.
    Implements alert suppression logic to prevent repetitive announcements:
        - Same track ID not re-announced within cooldown period (default 3s)
        - Re-announces if object moves to a new zone
        - Re-announces if distance changes by more than threshold (default 30%)
        - Object must be tracked for N frames before first announcement (stability)
    """

    def __init__(self, config: dict):
        """
        Initialize tracker with configuration.

        Args:
            config: Full config dict. Uses 'tracking' section.
        """
        track_config = config.get("tracking", {})
        self.cooldown_seconds = track_config.get("alert_cooldown_seconds", 3.0)
        self.re_announce_zone_change = track_config.get("re_announce_zone_change", True)
        self.distance_change_threshold = track_config.get("re_announce_distance_change_threshold", 0.30)
        self.min_tracked_frames = track_config.get("min_tracked_frames", 5)
        self.max_lost_frames = track_config.get("max_lost_frames", 30)

        # Internal state: track_id → tracking metadata
        self._track_state: dict[int, dict] = {}

        # Frame counter for consecutive frame verification
        self._frame_count = 0

        # Detection history: track_id → list of recent distances
        self._distance_history: dict[int, list[float]] = defaultdict(list)

        log.info(
            f"Tracker initialized — cooldown={self.cooldown_seconds}s, "
            f"min_frames={self.min_tracked_frames}, "
            f"distance_change_threshold={self.distance_change_threshold*100:.0f}%"
        )

    def update(self, detections: list[dict], frame_width: int) -> list[dict]:
        """
        Update tracker with new detections and return tracked objects.

        Since ByteTrack requires the Ultralytics results object, we implement
        a lightweight IoU-based tracker here that mimics ByteTrack behavior
        for the prototype. This avoids coupling to Ultralytics' internal
        tracking API which requires running model.track() instead of model().

        Args:
            detections: List of detection dicts from detector.py.
            frame_width: Frame width for direction context.

        Returns:
            List of tracked object dicts, each extending the detection dict with:
                - track_id (int): Persistent tracking ID
                - tracked_frames (int): Number of frames this object has been tracked
                - should_announce (bool): Whether this object should trigger a voice alert
                - alert_level (str): "urgent", "warning", "info", or "silent"
        """
        self._frame_count += 1
        current_time = time.time()

        # Simple IoU-based assignment
        tracked_objects = []
        matched_track_ids = set()

        for det in detections:
            # Find best matching existing track by IoU
            best_track_id = None
            best_iou = 0.3  # Minimum IoU threshold for matching

            for tid, state in self._track_state.items():
                if tid in matched_track_ids:
                    continue
                iou = self._compute_iou(det["bbox"], state["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = tid

            if best_track_id is not None:
                # Matched to existing track
                track_id = best_track_id
                matched_track_ids.add(track_id)
                self._track_state[track_id]["tracked_frames"] += 1
                self._track_state[track_id]["lost_frames"] = 0
            else:
                # New track
                track_id = self._next_track_id()
                self._track_state[track_id] = {
                    "tracked_frames": 1,
                    "lost_frames": 0,
                    "last_announced_time": 0.0,
                    "last_zone": None,
                    "last_distance": None,
                }

            state = self._track_state[track_id]

            # Update state
            state["bbox"] = det["bbox"]
            state["label"] = det["label"]

            # Store distance history for variance check
            distance = det.get("distance_m", -1.0)
            if distance > 0:
                self._distance_history[track_id].append(distance)
                # Keep only last 5 values
                if len(self._distance_history[track_id]) > 5:
                    self._distance_history[track_id] = self._distance_history[track_id][-5:]

            # Determine if this object should be announced
            should_announce = self._should_announce(
                track_id, det.get("direction", "CENTER"), distance, current_time
            )

            if should_announce:
                state["last_announced_time"] = current_time
                state["last_zone"] = det.get("direction", "CENTER")
                state["last_distance"] = distance

            tracked_obj = {
                **det,
                "track_id": track_id,
                "tracked_frames": state["tracked_frames"],
                "should_announce": should_announce,
            }
            tracked_objects.append(tracked_obj)

        # Increment lost_frames for unmatched tracks
        for tid in list(self._track_state.keys()):
            if tid not in matched_track_ids:
                self._track_state[tid]["lost_frames"] += 1
                # Remove if lost too long
                if self._track_state[tid]["lost_frames"] > self.max_lost_frames:
                    del self._track_state[tid]
                    if tid in self._distance_history:
                        del self._distance_history[tid]

        return tracked_objects

    def _should_announce(
        self, track_id: int, direction: str, distance: float, current_time: float
    ) -> bool:
        """
        Determine if a tracked object should trigger a voice alert.

        Conditions for announcement:
            1. Object tracked for ≥ min_tracked_frames (stability filter)
            2. Cooldown period elapsed since last announcement
            3. OR: zone changed, distance changed significantly, or new object

        Args:
            track_id: Persistent track ID.
            direction: Current zone (LEFT/CENTER/RIGHT).
            distance: Current estimated distance in meters.
            current_time: Current timestamp.

        Returns:
            True if the object should be announced.
        """
        state = self._track_state.get(track_id)
        if state is None:
            return False

        # Stability filter: must be tracked for enough frames
        if state["tracked_frames"] < self.min_tracked_frames:
            return False

        # Check if ever announced
        if state["last_announced_time"] == 0.0:
            return True  # First announcement

        time_since_last = current_time - state["last_announced_time"]

        # Cooldown not elapsed → check for significant changes
        if time_since_last < self.cooldown_seconds:
            # Zone change → re-announce
            if self.re_announce_zone_change and state["last_zone"] != direction:
                return True

            # Significant distance change → re-announce
            if (
                state["last_distance"] is not None
                and state["last_distance"] > 0
                and distance > 0
            ):
                distance_change = abs(distance - state["last_distance"]) / state["last_distance"]
                if distance_change > self.distance_change_threshold:
                    return True

            return False

        # Cooldown elapsed → allow announcement
        return True

    def get_distance_variance(self, track_id: int) -> float:
        """
        Get the coefficient of variation for recent distance measurements of a track.

        Used for distance stability verification.

        Args:
            track_id: Track ID to check.

        Returns:
            Coefficient of variation (std/mean). Returns 0.0 if insufficient data.
        """
        history = self._distance_history.get(track_id, [])
        if len(history) < 3:
            return 0.0

        import numpy as np
        values = np.array(history[-3:])  # Last 3 values
        mean = np.mean(values)
        if mean <= 0:
            return 0.0
        return float(np.std(values) / mean)

    @staticmethod
    def _compute_iou(bbox1: tuple, bbox2: tuple) -> float:
        """
        Compute Intersection over Union between two bounding boxes.

        Args:
            bbox1: (x1, y1, x2, y2) for box 1.
            bbox2: (x1, y1, x2, y2) for box 2.

        Returns:
            IoU value between 0.0 and 1.0.
        """
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        inter_area = max(0, x2 - x1) * max(0, y2 - y1)

        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

        union_area = area1 + area2 - inter_area
        if union_area <= 0:
            return 0.0

        return inter_area / union_area

    def _next_track_id(self) -> int:
        """Generate the next unique track ID."""
        if not self._track_state:
            return 1
        return max(self._track_state.keys()) + 1

    def reset(self):
        """Clear all tracking state."""
        self._track_state.clear()
        self._distance_history.clear()
        self._frame_count = 0
        log.info("Tracker state reset")
