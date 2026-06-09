# ============================================================
# modules/decision_engine.py — Rule-based navigation decision maker
# ============================================================

import time
from collections import defaultdict

from utils.logger import get_logger

log = get_logger("decision")

# ---- Hindi message templates (hardcoded, no LLM) ----
_HINDI_LABELS = {
    "person": "insaan",
    "chair": "kursi",
    "dining table": "mez",
    "table": "mez",
    "car": "gaadi",
    "bicycle": "cycle",
    "door": "darwaza",
    "stairs": "seedhiyan",
    "bench": "bench",
    "potted plant": "gamlaa",
    "backpack": "bag",
    "handbag": "bag",
    "suitcase": "suitcase",
    "bottle": "bottle",
    "cup": "cup",
    "laptop": "laptop",
    "cell phone": "phone",
    "book": "kitaab",
    "umbrella": "chhatri",
    "dog": "kutta",
    "cat": "billi",
    "bus": "bus",
    "truck": "truck",
    "motorcycle": "motorcycle",
    "fire hydrant": "hydrant",
    "stop sign": "stop sign",
    "couch": "sofa",
    "bed": "bistar",
    "toilet": "toilet",
    "tv": "TV",
    "wall": "diwaar",
}

_HINDI_DIRECTIONS = {
    "LEFT": "baayi taraf",
    "CENTER": "aage",
    "RIGHT": "daayi taraf",
}

_ENGLISH_DIRECTIONS = {
    "LEFT": "on your left",
    "CENTER": "ahead",
    "RIGHT": "on your right",
}


class Alert:
    """Represents a navigation alert to be spoken."""

    def __init__(
        self,
        level: str,
        message_en: str,
        message_hi: str,
        tracked_object: dict,
        priority_score: float = 0.0,
    ):
        self.level = level              # "urgent", "warning", "info"
        self.message_en = message_en
        self.message_hi = message_hi
        self.tracked_object = tracked_object
        self.priority_score = priority_score

    def get_message(self, language: str = "en") -> str:
        """Get the message in the specified language."""
        return self.message_hi if language == "hi" else self.message_en

    def __repr__(self):
        return f"Alert({self.level}, '{self.message_en}', score={self.priority_score:.2f})"


class DecisionEngine:
    """
    Rule-based navigation decision engine.

    Evaluates tracked objects and generates prioritized alerts:
        - URGENT (< 0.8m): "Stop immediately, obstacle very close"
        - WARNING (0.8–1.5m, CENTER): "Obstacle ahead, slow down"
        - INFO (1.5–2.5m): "{label} on your {direction}"
        - SILENT (> 2.5m): No announcement

    Anti-hallucination safeguards:
        - Multi-frame verification (3 consecutive frames required)
        - Distance stability check (≤20% variance)
        - Only objects with should_announce=True are considered

    Priority rules:
        1. Distance (closer = higher priority)
        2. CENTER > LEFT/RIGHT at same distance
        3. person/car get +0.5 priority boost (dynamic obstacles)
        4. Maximum 2 alerts per cycle
    """

    def __init__(self, config: dict):
        """
        Initialize decision engine with thresholds from config.

        Args:
            config: Full config dict. Uses 'decision' section.
        """
        dec_config = config.get("decision", {})
        thresholds = dec_config.get("thresholds", {})

        self.urgent_threshold = thresholds.get("urgent", 0.8)
        self.warning_threshold = thresholds.get("warning", 1.5)
        self.info_threshold = thresholds.get("info", 2.5)
        self.max_alerts = dec_config.get("max_simultaneous_alerts", 2)
        self.consecutive_frames = dec_config.get("consecutive_frames_required", 3)
        self.distance_variance_threshold = dec_config.get("distance_variance_threshold", 0.20)
        self.dynamic_labels = set(dec_config.get("dynamic_obstacle_labels", ["person", "car"]))

        # Reference to tracker for variance checks
        self._tracker = None

        # Category-level cooldown: tracks last announcement time per label only.
        # Keyed by label alone (not direction) so that zone-boundary jitter
        # between LEFT/CENTER/RIGHT cannot bypass the cooldown.
        self._category_last_announced: dict = {}   # key: label → timestamp
        self._category_cooldown: float = dec_config.get("category_cooldown_seconds", 8.0)

        log.info(
            f"Decision engine ready — urgent<{self.urgent_threshold}m, "
            f"warning<{self.warning_threshold}m, info<{self.info_threshold}m, "
            f"max_alerts={self.max_alerts}, category_cooldown={self._category_cooldown}s"
        )

    def set_tracker(self, tracker):
        """Set reference to the ObjectTracker for distance variance checks."""
        self._tracker = tracker

    def evaluate(self, tracked_objects: list[dict]) -> list[Alert]:
        """
        Evaluate tracked objects and generate prioritized navigation alerts.

        Applies three anti-spam mechanisms:
          1. Per-object tracker cooldown (should_announce from tracker)
          2. Multi-frame + distance stability verification
          3. Category-level cooldown: (label, direction) pair cannot repeat
             within category_cooldown_seconds regardless of track ID
          4. Same-class spatial grouping: multiple objects of the same label
             in the same direction are merged into a single "Multiple X" alert

        Args:
            tracked_objects: List of tracked object dicts from tracker.update().

        Returns:
            List of Alert objects, sorted by priority, max 2 items.
        """
        now = time.time()

        # ---- Step 1: Basic filtering (per-object checks) ----
        valid_objects = []
        for obj in tracked_objects:
            if not obj.get("should_announce", False):
                continue
            if obj.get("tracked_frames", 0) < self.consecutive_frames:
                continue
            if self._tracker is not None:
                variance = self._tracker.get_distance_variance(obj.get("track_id", -1))
                if variance > self.distance_variance_threshold:
                    log.debug(
                        f"Skipping {obj['label']} (ID:{obj.get('track_id')}) — "
                        f"distance variance {variance:.2f} > {self.distance_variance_threshold}"
                    )
                    continue
            valid_objects.append(obj)

        # ---- Step 2: Spatial grouping — group by (label, direction) ----
        # key: (label, direction) → list of objects in that group
        groups: dict = defaultdict(list)
        for obj in valid_objects:
            key = (obj.get("label", "obstacle"), obj.get("direction", "CENTER"))
            groups[key].append(obj)

        # ---- Step 3: Build one alert per group ----
        candidates = []
        for (label, direction), group_objs in groups.items():
            # Category-level cooldown check (keyed by label only — ignores direction
            # to prevent zone-boundary jitter from triggering a repeat announcement)
            last_time = self._category_last_announced.get(label, 0.0)
            if (now - last_time) < self._category_cooldown:
                log.debug(
                    f"Category cooldown active for '{label}' — "
                    f"{self._category_cooldown - (now - last_time):.1f}s remaining"
                )
                continue

            # Use the closest object in the group as the representative
            rep_obj = min(group_objs, key=lambda o: o.get("distance_m", 999.0))
            distance = rep_obj.get("distance_m", 999.0)
            count = len(group_objs)

            # Build alert with optional "Multiple X" prefix for groups > 1
            alert = self._create_alert(
                label=label,
                distance=distance,
                direction=direction,
                obj=rep_obj,
                count=count,
            )
            if alert is not None:
                candidates.append(alert)

        # ---- Step 4: Sort + limit + record category timestamps ----
        candidates.sort(key=lambda a: a.priority_score, reverse=True)
        final = candidates[: self.max_alerts]

        for alert in final:
            label_key = alert.tracked_object.get("label", "obstacle")
            self._category_last_announced[label_key] = now

        return final

    def _create_alert(
        self,
        label: str,
        distance: float,
        direction: str,
        obj: dict,
        count: int = 1,
    ) -> Alert | None:
        """
        Create an alert for a single object or a grouped set of same-class objects.

        Args:
            label:     COCO class name (e.g. "chair").
            distance:  Closest distance in the group (meters).
            direction: Shared direction of the group.
            obj:       Representative object dict (closest one in group).
            count:     Number of objects in this group (1 = single object).

        Returns:
            Alert instance, or None if SILENT (distance > info_threshold).
        """
        # ---- Priority score ----
        priority = 10.0 / max(distance, 0.1)

        if direction == "CENTER":
            priority += 2.0
        if label in self.dynamic_labels:
            priority += 0.5

        # ---- Build message prefix (singular vs multiple) ----
        en_dir = _ENGLISH_DIRECTIONS.get(direction, "ahead")
        hi_label = _HINDI_LABELS.get(label, label)
        hi_dir = _HINDI_DIRECTIONS.get(direction, "aage")

        if count > 1:
            # Grouped: "Multiple chairs ahead"
            label_en = f"Multiple {label}s"
            label_hi = f"Kai {hi_label}"
        else:
            label_en = label.capitalize()
            label_hi = hi_label.capitalize()

        # ---- Alert level ----
        if distance < self.urgent_threshold:
            level = "urgent"
            message_en = f"{label_en} very close {en_dir}."
            message_hi = f"{label_hi} bahut paas {hi_dir}."
            priority += 20.0  # Massive boost for urgent

        elif distance < self.warning_threshold:
            level = "warning"
            message_en = f"{label_en} close {en_dir}."
            message_hi = f"{label_hi} paas {hi_dir}."
            priority += 5.0

        elif distance < self.info_threshold:
            level = "info"
            message_en = f"{label_en} nearby {en_dir}."
            message_hi = f"{label_hi} nazdeek {hi_dir}."

        else:
            # SILENT — no alert
            return None

        # Tag representative object with alert level for frame annotation
        obj["alert_level"] = level

        return Alert(
            level=level,
            message_en=message_en,
            message_hi=message_hi,
            tracked_object=obj,
            priority_score=priority,
        )
