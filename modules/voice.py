# ============================================================
# modules/voice.py — Async bilingual TTS engine
# ============================================================

import os
import queue
import tempfile
import threading
import time
import uuid

from utils.logger import get_logger

log = get_logger("voice")


class VoiceEngine:
    """
    Asynchronous bilingual text-to-speech engine.

    - English: pyttsx3 (fully offline, fast)
    - Hindi: gTTS → temp MP3 → pygame.mixer playback (requires internet)

    Runs in a dedicated daemon thread with a message queue.
    Never blocks the main vision pipeline.
    """

    def __init__(self, config: dict):
        """
        Initialize TTS engines and start the background worker thread.

        Args:
            config: Full config dict. Uses 'voice' section.
        """
        voice_config = config.get("voice", {})
        self._language = voice_config.get("default_language", "en")
        self._rate = voice_config.get("pyttsx3_rate", 175)
        self._volume = voice_config.get("pyttsx3_volume", 1.0)
        self._gtts_lang = voice_config.get("gtts_lang", "hi")
        self._queue_max_size = voice_config.get("queue_max_size", 10)
        self._temp_dir = voice_config.get("audio_temp_dir", "temp_audio")

        # Create temp audio directory
        os.makedirs(self._temp_dir, exist_ok=True)

        # Message queue
        self._queue: queue.Queue = queue.Queue(maxsize=self._queue_max_size)

        # Thread control
        self._running = False
        self._thread: threading.Thread | None = None

        # pyttsx3 engine (created in worker thread for thread safety)
        self._pyttsx3_engine = None

        # pygame mixer (initialized in worker thread)
        self._pygame_initialized = False

        log.info(f"Voice engine configured — language={self._language}, rate={self._rate}")

    def start(self):
        """Start the background TTS worker thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="VoiceWorker")
        self._thread.start()
        log.info("Voice worker thread started")

    def stop(self):
        """Gracefully stop the TTS worker thread."""
        self._running = False
        # Send sentinel to unblock queue
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        # Cleanup temp files
        self._cleanup_temp_files()
        log.info("Voice engine stopped")

    def speak(self, message: str, language: str | None = None):
        """
        Enqueue a message for TTS playback (non-blocking).

        If the queue is full, the oldest message is discarded to make room.

        Args:
            message: Text to speak.
            language: Language override ("en" or "hi"). Uses current language if None.
        """
        lang = language or self._language

        try:
            self._queue.put_nowait({"text": message, "lang": lang})
        except queue.Full:
            # Discard oldest and add new
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait({"text": message, "lang": lang})
            except queue.Full:
                log.warning(f"Voice queue full, dropping message: {message[:50]}")

    def toggle_language(self) -> str:
        """
        Toggle between English and Hindi.

        Returns:
            New language code ("en" or "hi").
        """
        self._language = "hi" if self._language == "en" else "en"
        lang_name = "Hindi" if self._language == "hi" else "English"
        log.info(f"Language toggled to: {lang_name}")

        # Announce the language change
        if self._language == "en":
            self.speak("Switched to English.", "en")
        else:
            self.speak("Hindi mein badal gaya.", "hi")

        return self._language

    def get_language(self) -> str:
        """Get the current language code."""
        return self._language

    def _worker(self):
        """
        Background worker thread that processes the TTS queue.

        Initializes pygame in this thread for thread safety.
        pyttsx3 is re-initialized per utterance to avoid the Windows
        SAPI5 bug where runAndWait() freezes after first use in a
        daemon thread.
        """
        # Initialize pygame mixer in this thread
        try:
            import pygame
            pygame.mixer.init()
            self._pygame_initialized = True
            log.info("pygame mixer initialized")
        except Exception as e:
            log.error(f"Failed to initialize pygame mixer: {e}")
            self._pygame_initialized = False

        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                # Sentinel — shutdown signal
                break

            text = item["text"]
            lang = item["lang"]

            try:
                if lang == "hi":
                    self._speak_hindi(text)
                else:
                    self._speak_english(text)
            except Exception as e:
                log.error(f"TTS error ({lang}): {e}")

        log.debug("Voice worker thread exiting")

    def _speak_english(self, text: str):
        """
        Speak English text using pyttsx3 (offline).

        Re-initializes the pyttsx3 engine for EACH utterance to work
        around the Windows SAPI5 bug where runAndWait() silently stops
        working after the first call in a daemon thread.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)
            log.debug(f"Speaking (EN): {text}")
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            log.error(f"pyttsx3 speak error: {e}")

    def _speak_hindi(self, text: str):
        """Speak Hindi text using gTTS + pygame (requires internet)."""
        if not self._pygame_initialized:
            log.warning(f"pygame unavailable, cannot speak Hindi: {text}")
            # Fallback to English engine with transliterated text
            self._speak_english(text)
            return

        try:
            from gtts import gTTS
            import pygame

            log.debug(f"Speaking (HI): {text}")

            # Generate MP3 to temp file
            filename = os.path.join(self._temp_dir, f"hi_{uuid.uuid4().hex[:8]}.mp3")
            tts = gTTS(text=text, lang=self._gtts_lang)
            tts.save(filename)

            # Play with pygame
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()

            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)

            # Cleanup
            pygame.mixer.music.unload()
            try:
                os.remove(filename)
            except OSError:
                pass

        except ImportError:
            log.error("gTTS not installed — Hindi TTS unavailable")
            self._speak_english(text)
        except Exception as e:
            log.error(f"Hindi TTS error: {e}")
            # Fallback to English
            self._speak_english(text)

    def _cleanup_temp_files(self):
        """Remove any leftover temp audio files."""
        if os.path.exists(self._temp_dir):
            for f in os.listdir(self._temp_dir):
                try:
                    os.remove(os.path.join(self._temp_dir, f))
                except OSError:
                    pass
