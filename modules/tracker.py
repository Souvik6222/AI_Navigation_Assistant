# ============================================================
# modules/tracker.py — Object tracking with Hungarian assignment
# ============================================================
#
# Upgraded from greedy IoU matching to:
#   - Hungarian algorithm (scipy) for globally optimal assignment
#   - Linear velocity prediction for occlusion-robust matching
#   - Velocity estimation (get_velocity) for approach detection
# ============================================================

import time
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from utils.logger import get_logger

log = get_logger("tracker")


class ObjectTracker:
    """
    Object tracker with Hungarian (optimal) assignment.

    Assigns persistent track IDs to detected objects across frames.
    Uses linear velocity prediction to extrapolate bounding box positions,
    then solves optimal IoU assignment via the Hungarian algorithm.

    Implements alert suppression logic to prevent repetitive announcements:
        - Same track ID not re-announced within cooldown period (default 7s)
        - Re-announces if object moves to a new zone
        - Re-announces if distance changes by more than threshold (default 50%)
        - Object must be tracked for N frames before first announcement (stability)
    """

    def __init__(self, config: dict):
        """
        Initialize tracker with configuration.

        Args:
            config: Full config dict. Uses 'tracking' section.
        """
        track_config = config.get("tracking", {})
        self.cooldown_seconds = track_config.get("alert_cooldown_seconds", 7.0)
        self.re_announce_zone_change = track_config.get("re_announce_zone_change", True)
        self.distance_change_threshold = track_config.get("re_announce_distance_change_threshold", 0.50)
        self.min_tracked_frames = track_config.get("min_tracked_frames", 5)
        self.max_lost_frames = track_config.get("max_lost_frames", 30)
        self.iou_threshold = 0.2  # Minimum IoU for a valid match

        # Internal state: track_id → tracking metadata
        self._track_state: dict[int, dict] = {}

        # Frame counter
        self._frame_count = 0

        # Detection history: track_id → list of recent distances
        self._distance_history: dict[int, list[float]] = defaultdict(list)

        # Timestamp history: track_id → list of recent timestamps
        self._time_history: dict[int, list[float]] = defaultdict(list)

        # Next track ID counter (monotonic, avoids max() scan each frame)
        self._next_id = 1

        log.info(
            f"Tracker initialized (Hungarian) — cooldown={self.cooldown_seconds}s, "
            f"min_frames={self.min_tracked_frames}, "
            f"distance_change_threshold={self.distance_change_threshold*100:.0f}%"
        )

    def update(self, detections: list[dict], frame_width: int) -> list[dict]:
        """
        Update tracker with new detections and return tracked objects.

        Uses the Hungarian algorithm (scipy.optimize.linear_sum_assignment)
        for globally optimal IoU-based assignment. Bounding boxes from
        existing tracks are predicted forward using linear velocity before
        matching to improve robustness during brief occlusions.

        Args:
            detections: List of detection dicts from detector.py.
            frame_width: Frame width for direction context.

        Returns:
            List of tracked object dicts, each extending the detection dict with:
                - track_id (int): Persistent tracking ID
                - tracked_frames (int): Number of frames this object has been tracked
                - should_announce (bool): Whether this object should trigger a voice alert
        """
        self._frame_count += 1
        current_time = time.time()

        matched_track_ids = set()
        det_to_track: dict[int, int] = {}  # detection index → track_id

        active_track_ids = [
            tid for tid, state in self._track_state.items()
            if state["lost_frames"] < self.max_lost_frames
        ]

        # ---- Hungarian assignment ----
        if detections and active_track_ids:
            n_det = len(detections)
            n_tracks = len(active_track_ids)

            # Build cost matrix (1 - IoU; lower is better for minimisation)
            cost_matrix = np.ones((n_det, n_tracks), dtype=np.float64)

            for di, det in enumerate(detections):
                for ti, tid in enumerate(active_track_ids):
                    state = self._track_state[tid]
                    predicted_bbox = self._predict_bbox(state)
                    iou = self._compute_iou(det["bbox"], predicted_bbox)
                    cost_matrix[di, ti] = 1.0 - iou

            # Solve optimal assignment
            row_indices, col_indices = linear_sum_assignment(cost_matrix)

            for di, ti in zip(row_indices, col_indices):
                iou = 1.0 - cost_matrix[di, ti]
                if iou >= self.iou_threshold:
                    track_id = active_track_ids[ti]
                    det_to_track[di] = track_id
                    matched_track_ids.add(track_id)

                    state = self._track_state[track_id]
                    old_bbox = state["bbox"]
                    new_bbox = detections[di]["bbox"]

                    # Update velocity estimate (bbox center displacement)
                    dt = current_time - state.get("last_update_time", current_time)
                    if dt > 0.001:
                        old_cx = (old_bbox[0] + old_bbox[2]) / 2.0
                        old_cy = (old_bbox[1] + old_bbox[3]) / 2.0
                        new_cx = (new_bbox[0] + new_bbox[2]) / 2.0
                        new_cy = (new_bbox[1] + new_bbox[3]) / 2.0
                        state["vel_x"] = (new_cx - old_cx) / dt
                        state["vel_y"] = (new_cy - old_cy) / dt

                    state["tracked_frames"] += 1
                    state["lost_frames"] = 0
                    state["bbox"] = new_bbox
                    state["label"] = detections[di]["label"]
                    state["last_update_time"] = current_time

        # ---- Handle unmatched detections → new tracks ----
        for di, det in enumerate(detections):
            if di in det_to_track:
                continue

            track_id = self._next_id
            self._next_id += 1

            self._track_state[track_id] = {
                "tracked_frames": 1,
                "lost_frames": 0,
                "last_announced_time": 0.0,
                "last_zone": None,
                "last_distance": None,
                "bbox": det["bbox"],
                "label": det["label"],
                "vel_x": 0.0,
                "vel_y": 0.0,
                "last_update_time": current_time,
            }
            det_to_track[di] = track_id
            matched_track_ids.add(track_id)

        # ---- Build tracked_objects output ----
        tracked_objects = []

        for di, det in enumerate(detections):
            track_id = det_to_track.get(di)
            if track_id is None:
                continue

            state = self._track_state[track_id]

            # Store distance history for variance check
            distance = det.get("distance_m", -1.0)
            if distance > 0:
                self._distance_history[track_id].append(distance)
                self._time_history[track_id].append(current_time)
                # Keep only last 10 values
                if len(self._distance_history[track_id]) > 10:
                    self._distance_history[track_id] = self._distance_history[track_id][-10:]
                    self._time_history[track_id] = self._time_history[track_id][-10:]

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

        # ---- Increment lost_frames for unmatched tracks ----
        for tid in list(self._track_state.keys()):
            if tid not in matched_track_ids:
                self._track_state[tid]["lost_frames"] += 1
                if self._track_state[tid]["lost_frames"] > self.max_lost_frames:
                    del self._track_state[tid]
                    self._distance_history.pop(tid, None)
                    self._time_history.pop(tid, None)

        return tracked_objects

    def _predict_bbox(self, state: dict) -> tuple:
        """
        Predict bounding box position using linear velocity extrapolation.

        If the track has velocity estimates, extrapolate the bbox center
        forward by the time elapsed since the last update.

        Args:
            state: Track state dict.

        Returns:
            Predicted bounding box as (x1, y1, x2, y2).
        """
        bbox = state.get("bbox", (0, 0, 0, 0))
        vel_x = state.get("vel_x", 0.0)
        vel_y = state.get("vel_y", 0.0)
        last_t = state.get("last_update_time", 0.0)
        now = time.time()
        dt = now - last_t

        if (abs(vel_x) < 1e-6 and abs(vel_y) < 1e-6) or dt > 1.0:
            return bbox

        x1, y1, x2, y2 = bbox
        dx = vel_x * dt
        dy = vel_y * dt
        return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

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

        if state["tracked_frames"] < self.min_tracked_frames:
            return False

        if state["last_announced_time"] == 0.0:
            return True  # First announcement

        time_since_last = current_time - state["last_announced_time"]

        if time_since_last < self.cooldown_seconds:
            if self.re_announce_zone_change and state["last_zone"] != direction:
                return True

            if (
                state["last_distance"] is not None
                and state["last_distance"] > 0
                and distance > 0
            ):
                distance_change = abs(distance - state["last_distance"]) / state["last_distance"]
                if distance_change > self.distance_change_threshold:
                    return True

            return False

        return True

    def get_distance_variance(self, track_id: int) -> float:
        """
        Get the coefficient of variation for recent distance measurements.

        Used for distance stability verification (anti-hallucination layer 6).

        Args:
            track_id: Track ID to check.

        Returns:
            Coefficient of variation (std/mean). Returns 0.0 if insufficient data.
        """
        history = self._distance_history.get(track_id, [])
        if len(history) < 3:
            return 0.0

        values = np.array(history[-5:])
        mean = np.mean(values)
        if mean <= 0:
            return 0.0
        return float(np.std(values) / mean)

    def get_velocity(self, track_id: int) -> float:
        """
        Get the rate of distance change (m/s) for a tracked object.

        Positive = receding (moving away).
        Negative = approaching (moving closer).
        Zero = stationary or insufficient data.

        Uses linear regression over recent distance/time history.

        Args:
            track_id: Track ID to check.

        Returns:
            Distance velocity in m/s. Negative means approaching.
        """
        dist_hist = self._distance_history.get(track_id, [])
        time_hist = self._time_history.get(track_id, [])

        if len(dist_hist) < 3 or len(time_hist) < 3:
            return 0.0

        distances = np.array(dist_hist[-5:])
        times = np.array(time_hist[-5:])
        times = times - times[0]  # Normalise

        if times[-1] - times[0] < 0.1:
            return 0.0

        # Linear regression: slope of distance vs time
        n = len(times)
        sum_t = np.sum(times)
        sum_d = np.sum(distances)
        sum_td = np.sum(times * distances)
        sum_t2 = np.sum(times * times)

        denom = n * sum_t2 - sum_t * sum_t
        if abs(denom) < 1e-10:
            return 0.0

        slope = (n * sum_td - sum_t * sum_d) / denom
        return float(slope)

    def get_motion_state(self, track_id: int) -> str:
        """
        Classify the motion state of a tracked object.

        Returns:
            "APPROACHING" if closing at > 0.1 m/s
            "RECEDING" if moving away at > 0.1 m/s
            "STATIONARY" otherwise
        """
        velocity = self.get_velocity(track_id)
        if velocity < -0.1:
            return "APPROACHING"
        elif velocity > 0.1:
            return "RECEDING"
        return "STATIONARY"

    @staticmethod
    def _compute_iou(bbox1: tuple, bbox2: tuple) -> float:
        """Compute Intersection over Union between two bounding boxes."""
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

    def reset(self):
        """Clear all tracking state."""
        self._track_state.clear()
        self._distance_history.clear()
        self._time_history.clear()
        self._frame_count = 0
        self._next_id = 1
        log.info("Tracker state reset")
