# ============================================================
# modules/camera.py — Threaded camera reader (zero-lag)
# ============================================================
# Runs cv2.VideoCapture.read() in a background daemon thread,
# always keeping only the most recent frame.  The main AI loop
# calls camera.read() to get the latest frame instantly — no
# buffering delay from the IP camera stream.
# ============================================================

import threading
import time

import cv2
import numpy as np

from utils.logger import get_logger

log = get_logger("camera")


class CameraStream:
    """
    Threaded camera reader that always holds the latest frame.

    The background thread continuously calls cap.read() and
    overwrites a single shared frame buffer.  This ensures:
      1. The main loop never waits for I/O.
      2. Old buffered frames from the IP camera are discarded,
         so the AI always processes the *current* scene.

    Usage:
        cam = CameraStream(source, width, height)
        cam.start()
        ...
        ret, frame = cam.read()   # instant, never blocks
        ...
        cam.stop()
    """

    def __init__(self, source, width: int = 640, height: int = 480):
        """
        Initialize the camera stream.

        Args:
            source: Camera device index (int) or IP stream URL (str).
            width:  Desired frame width.
            height: Desired frame height.
        """
        self.source = source
        self.width = width
        self.height = height

        self._cap = cv2.VideoCapture(source)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Reduce internal OpenCV buffer to 1 frame (if the backend supports it)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ret: bool = False
        self._running: bool = False
        self._thread: threading.Thread | None = None

    def is_opened(self) -> bool:
        """Check if the underlying VideoCapture is opened."""
        return self._cap.isOpened()

    def start(self):
        """Start the background frame-grabbing thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="CameraReaderThread",
        )
        self._thread.start()
        log.info(f"Camera stream started — source={self.source}")

    def read(self) -> tuple[bool, np.ndarray | None]:
        """
        Return the most recent frame (non-blocking).

        Returns:
            (success_bool, frame_or_None)
        """
        with self._lock:
            return self._ret, self._frame.copy() if self._frame is not None else None

    def stop(self):
        """Stop the reader thread and release the camera."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
        log.info("Camera stream stopped")

    def release(self):
        """Alias for stop() — drop-in replacement for cv2.VideoCapture."""
        self.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reader_loop(self):
        """Continuously grab frames, keeping only the latest one."""
        while self._running:
            ret, frame = self._cap.read()
            with self._lock:
                self._ret = ret
                self._frame = frame
            if not ret:
                # Brief pause on failure to avoid busy-spin
                time.sleep(0.05)
