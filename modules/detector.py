# ============================================================
# modules/detector.py — YOLOv8 object detection wrapper
# ============================================================

import numpy as np
from ultralytics import YOLO
from utils.logger import get_logger

log = get_logger("detector")

# COCO class name mapping (subset relevant for navigation)
# Full COCO has 80 classes; we whitelist only navigation-relevant ones
COCO_NAVIGATION_CLASSES = {
    0: "person",
    13: "bench",
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    41: "cup",
    56: "chair",
    57: "couch",
    58: "potted plant",
    59: "bed",
    60: "dining table",
    61: "toilet",
    62: "tv",
    63: "laptop",
    67: "cell phone",
    73: "book",
    2: "car",
    1: "bicycle",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    9: "traffic light",
    10: "fire hydrant",
    11: "stop sign",
    15: "cat",
    16: "dog",
}


class ObjectDetector:
    """
    YOLOv8 wrapper for real-time multi-object detection.

    Filters detections by:
        - Confidence threshold (default ≥ 0.80)
        - Class whitelist (navigation-relevant objects only)
        - Minimum bounding box area (≥ 1% of frame area)
    """

    def __init__(self, config: dict):
        """
        Initialize the YOLOv8 model.

        Args:
            config: Full config dict. Uses 'detection' section for:
                model_path, confidence_threshold, min_bbox_area_ratio, target_classes
        """
        det_config = config.get("detection", {})
        self.model_path = det_config.get("model_path", "yolov8x.pt")
        self.confidence_threshold = det_config.get("confidence_threshold", 0.80)
        self.min_bbox_area_ratio = det_config.get("min_bbox_area_ratio", 0.01)
        self.target_class_names = set(det_config.get("target_classes", COCO_NAVIGATION_CLASSES.values()))

        log.info(f"Loading YOLOv8 model: {self.model_path}")
        self.model = YOLO(self.model_path)

        # Build set of target class IDs from model's class names
        self.target_class_ids = set()
        if hasattr(self.model, "names"):
            for class_id, class_name in self.model.names.items():
                if class_name in self.target_class_names:
                    self.target_class_ids.add(class_id)

        log.info(
            f"Detector ready — conf≥{self.confidence_threshold}, "
            f"{len(self.target_class_ids)} target classes, "
            f"min bbox area≥{self.min_bbox_area_ratio*100:.0f}%"
        )

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Run YOLOv8 inference on a single frame.

        Args:
            frame: Input BGR frame (numpy array).

        Returns:
            List of detection dicts, each containing:
                - label (str): Class name
                - confidence (float): Detection confidence 0–1
                - bbox (tuple): (x1, y1, x2, y2) pixel coordinates
                - center_x (float): Horizontal center of bbox
                - center_y (float): Vertical center of bbox
                - area (float): Bbox area in pixels
                - class_id (int): COCO class ID
        """
        frame_h, frame_w = frame.shape[:2]
        frame_area = frame_h * frame_w
        min_area = frame_area * self.min_bbox_area_ratio

        # Run inference with class filter
        results = self.model(
            frame,
            conf=self.confidence_threshold,
            classes=list(self.target_class_ids) if self.target_class_ids else None,
            verbose=False,
        )

        detections = []

        for result in results:
            if result.boxes is None:
                continue

            boxes = result.boxes
            for i in range(len(boxes)):
                # Extract values
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(float)
                confidence = float(boxes.conf[i].cpu().numpy())
                class_id = int(boxes.cls[i].cpu().numpy())

                # Get class name
                label = self.model.names.get(class_id, f"class_{class_id}")

                # Calculate area
                bbox_area = (x2 - x1) * (y2 - y1)

                # Filter: minimum bounding box area (anti-noise)
                if bbox_area < min_area:
                    continue

                # Filter: whitelist check (redundant safety)
                if label not in self.target_class_names:
                    continue

                detections.append({
                    "label": label,
                    "confidence": confidence,
                    "bbox": (x1, y1, x2, y2),
                    "center_x": (x1 + x2) / 2.0,
                    "center_y": (y1 + y2) / 2.0,
                    "area": bbox_area,
                    "class_id": class_id,
                })

        return detections

    def swap_model(self, model_path: str):
        """
        Hot-swap the YOLO model at runtime.

        Loads a new model and rebuilds the target class ID set.
        Called from the dashboard when the user selects a different model.

        Args:
            model_path: Path to the new YOLO model file (e.g., "yolov8n.pt").
        """
        log.info(f"Hot-swapping YOLO model to: {model_path}")
        self.model = YOLO(model_path)
        self.model_path = model_path
        # Rebuild target class IDs for new model
        self.target_class_ids = set()
        if hasattr(self.model, "names"):
            for class_id, class_name in self.model.names.items():
                if class_name in self.target_class_names:
                    self.target_class_ids.add(class_id)
        log.info(f"Model swapped successfully: {model_path}")
