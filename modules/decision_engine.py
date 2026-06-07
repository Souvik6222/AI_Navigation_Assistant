# ============================================================
# modules/decision_engine.py — Rule-based navigation decision maker
# ============================================================

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

        log.info(
            f"Decision engine ready — urgent<{self.urgent_threshold}m, "
            f"warning<{self.warning_threshold}m, info<{self.info_threshold}m, "
            f"max_alerts={self.max_alerts}"
        )

    def set_tracker(self, tracker):
        """Set reference to the ObjectTracker for distance variance checks."""
        self._tracker = tracker

    def evaluate(self, tracked_objects: list[dict]) -> list[Alert]:
        """
        Evaluate tracked objects and generate prioritized navigation alerts.

        Args:
            tracked_objects: List of tracked object dicts from tracker.update().

        Returns:
            List of Alert objects, sorted by priority, max 2 items.
        """
        candidates = []

        for obj in tracked_objects:
            # Only consider objects that tracker says should be announced
            if not obj.get("should_announce", False):
                continue

            # Multi-frame verification
            if obj.get("tracked_frames", 0) < self.consecutive_frames:
                continue

            # Distance stability check
            if self._tracker is not None:
                variance = self._tracker.get_distance_variance(obj.get("track_id", -1))
                if variance > self.distance_variance_threshold:
                    log.debug(
                        f"Skipping {obj['label']} (ID:{obj.get('track_id')}) — "
                        f"distance variance {variance:.2f} > {self.distance_variance_threshold}"
                    )
                    continue

            distance = obj.get("distance_m", 999.0)
            direction = obj.get("direction", "CENTER")
            label = obj.get("label", "obstacle")

            # Determine alert level and generate messages
            alert = self._create_alert(label, distance, direction, obj)
            if alert is not None:
                candidates.append(alert)

        # Sort by priority (highest first) and return top N
        candidates.sort(key=lambda a: a.priority_score, reverse=True)
        return candidates[: self.max_alerts]

    def _create_alert(
        self, label: str, distance: float, direction: str, obj: dict
    ) -> Alert | None:
        """
        Create an alert for a single object based on distance rules.

        Returns None for SILENT level (distance > info_threshold).
        """
        # Calculate priority score
        # Base: inverse distance (closer = higher)
        priority = 10.0 / max(distance, 0.1)

        # Bonus for CENTER direction
        if direction == "CENTER":
            priority += 2.0

        # Bonus for dynamic obstacles
        if label in self.dynamic_labels:
            priority += 0.5

        # Determine level and messages
        en_dir = _ENGLISH_DIRECTIONS.get(direction, "ahead")
        hi_label = _HINDI_LABELS.get(label, label)
        hi_dir = _HINDI_DIRECTIONS.get(direction, "aage")

        if distance < self.urgent_threshold:
            level = "urgent"
            message_en = f"{label.capitalize()} very close {en_dir}."
            message_hi = f"{hi_label} bahut paas {hi_dir}."
            priority += 20.0  # Massive boost for urgent

        elif distance < self.warning_threshold:
            level = "warning"
            message_en = f"{label.capitalize()} close {en_dir}."
            message_hi = f"{hi_label} paas {hi_dir}."
            priority += 5.0

        elif distance < self.info_threshold:
            level = "info"
            message_en = f"{label.capitalize()} nearby {en_dir}."
            message_hi = f"{hi_label} nazdeek {hi_dir}."

        else:
            # SILENT — no alert
            return None

        # Tag object with alert level for annotation
        obj["alert_level"] = level

        return Alert(
            level=level,
            message_en=message_en,
            message_hi=message_hi,
            tracked_object=obj,
            priority_score=priority,
        )
