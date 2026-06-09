# ============================================================
# modules/voice.py — Async bilingual TTS engine
# ============================================================
#
# Latency improvements:
#   - pyttsx3 engine is created ONCE and reused (not re-init per utterance)
#   - Hindi TTS uses pyttsx3 with espeak-ng (fully offline)
#   - Falls back to gTTS only if espeak-ng Hindi is unavailable
#   - Platform-specific workaround for Windows SAPI5 bug
# ============================================================

import os
import queue
import sys
import threading
import time
import uuid

from utils.logger import get_logger

log = get_logger("voice")

# Check if we're on Windows (SAPI5 has a known bug with daemon threads)
_IS_WINDOWS = sys.platform.startswith("win")


class VoiceEngine:
    """
    Asynchronous bilingual text-to-speech engine.

    - English: pyttsx3 (fully offline, fast, engine reused)
    - Hindi: pyttsx3 with espeak-ng Hindi voice (offline), falls back to gTTS

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

        # pyttsx3 engine (created once in worker thread for thread safety)
        self._pyttsx3_engine = None

        # Hindi TTS mode: "espeak" (offline) or "gtts" (online fallback)
        self._hindi_mode: str = "espeak"

        # pygame mixer (initialized in worker thread only if needed for gTTS)
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

    def speak(self, message: str, language: str | None = None, urgent: bool = False):
        """
        Enqueue a message for TTS playback (non-blocking).

        If urgent=True, the queue is cleared of all pending non-urgent
        messages first so the urgent alert plays immediately.

        If the queue is full (non-urgent), the oldest message is discarded.

        Args:
            message:  Text to speak.
            language: Language override ("en" or "hi"). Uses current language if None.
            urgent:   If True, clears stale messages from queue before enqueuing.
        """
        lang = language or self._language
        item = {"text": message, "lang": lang, "urgent": urgent}

        if urgent:
            # Wipe the queue of all pending messages so urgent alert plays NOW
            cleared = 0
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    cleared += 1
                except queue.Empty:
                    break
            if cleared:
                log.debug(f"Urgent alert: cleared {cleared} stale messages from queue")

        try:
            self._queue.put_nowait(item)
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

        Initialises pyttsx3 ONCE and reuses it for all utterances.
        On Windows, falls back to re-init per utterance due to SAPI5 bug.
        """
        # ---- Initialize pyttsx3 engine (once) ----
        self._init_pyttsx3()

        # ---- Check if espeak-ng has Hindi support ----
        self._check_hindi_support()

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

    def _init_pyttsx3(self):
        """Initialize the pyttsx3 engine (called once in worker thread)."""
        try:
            import pyttsx3
            self._pyttsx3_engine = pyttsx3.init()
            self._pyttsx3_engine.setProperty("rate", self._rate)
            self._pyttsx3_engine.setProperty("volume", self._volume)
            log.info("pyttsx3 engine initialized (persistent)")
        except Exception as e:
            log.error(f"Failed to initialize pyttsx3: {e}")
            self._pyttsx3_engine = None

    def _check_hindi_support(self):
        """
        Check if pyttsx3/espeak-ng supports Hindi.
        If available, use offline Hindi. Otherwise fall back to gTTS.
        """
        if self._pyttsx3_engine is None:
            self._hindi_mode = "gtts"
            return

        try:
            voices = self._pyttsx3_engine.getProperty("voices")
            hindi_voice = None
            for voice in voices:
                # espeak-ng Hindi voice IDs typically contain "hi" or "hindi"
                voice_id = voice.id.lower() if voice.id else ""
                voice_name = voice.name.lower() if voice.name else ""
                langs = [l.lower() if isinstance(l, str) else "" for l in (voice.languages or [])]
                lang_str = " ".join(langs)

                if ("hindi" in voice_name or "hindi" in voice_id or
                    voice_id.endswith("/hi") or "/hi" in voice_id or
                    "hi" in lang_str):
                    hindi_voice = voice
                    break

            if hindi_voice:
                self._hindi_voice_id = hindi_voice.id
                self._hindi_mode = "espeak"
                log.info(f"Hindi TTS: offline via espeak-ng (voice={hindi_voice.id})")
            else:
                self._hindi_mode = "gtts"
                log.warning("Hindi TTS: espeak-ng Hindi voice not found — will try gTTS (requires internet)")
                # Initialize pygame for gTTS fallback
                self._init_pygame()

        except Exception as e:
            log.warning(f"Could not check Hindi voices: {e}")
            self._hindi_mode = "gtts"
            self._init_pygame()

    def _init_pygame(self):
        """Initialize pygame mixer for gTTS audio playback."""
        if self._pygame_initialized:
            return
        try:
            import pygame
            pygame.mixer.init()
            self._pygame_initialized = True
            log.info("pygame mixer initialized (for gTTS fallback)")
        except Exception as e:
            log.error(f"Failed to initialize pygame mixer: {e}")
            self._pygame_initialized = False

    def _speak_english(self, text: str):
        """
        Speak English text using pyttsx3 (offline).

        Reuses the persistent engine. On Windows, re-initialises per
        utterance to work around the SAPI5 daemon thread bug.
        """
        if _IS_WINDOWS:
            # Windows SAPI5 workaround: re-init per utterance
            self._speak_with_fresh_engine(text)
            return

        # Linux / macOS: reuse persistent engine
        if self._pyttsx3_engine is None:
            self._init_pyttsx3()

        if self._pyttsx3_engine is None:
            log.error("pyttsx3 engine unavailable, cannot speak")
            return

        try:
            log.debug(f"Speaking (EN): {text}")
            self._pyttsx3_engine.say(text)
            self._pyttsx3_engine.runAndWait()
        except Exception as e:
            log.warning(f"pyttsx3 runAndWait failed, re-initialising: {e}")
            # If persistent engine breaks, re-init and retry once
            self._init_pyttsx3()
            if self._pyttsx3_engine:
                try:
                    self._pyttsx3_engine.say(text)
                    self._pyttsx3_engine.runAndWait()
                except Exception as e2:
                    log.error(f"pyttsx3 retry failed: {e2}")

    def _speak_hindi(self, text: str):
        """
        Speak Hindi text.

        Tries gTTS (natural voice, requires internet) first.
        Falls back to espeak-ng (offline) if available.
        If both fail, speaks the text with the English engine.
        """
        if self._hindi_mode == "gtts" or self._hindi_mode == "espeak":
            if self._speak_hindi_gtts(text):
                return

        if self._hindi_voice_id:
            self._speak_hindi_espeak(text)
        else:
            log.warning("No Hindi TTS backend available, falling back to English")
            self._speak_english(text)

    def _speak_hindi_espeak(self, text: str):
        """Speak Hindi using pyttsx3 with espeak-ng Hindi voice (fully offline)."""
        if self._pyttsx3_engine is None:
            log.warning("pyttsx3 unavailable for Hindi, falling back to English")
            self._speak_english(text)
            return

        try:
            log.debug(f"Speaking (HI-espeak): {text}")
            # Temporarily switch to Hindi voice
            original_voice = self._pyttsx3_engine.getProperty("voice")
            self._pyttsx3_engine.setProperty("voice", self._hindi_voice_id)
            # Hindi speech rate slightly slower for clarity
            self._pyttsx3_engine.setProperty("rate", max(self._rate - 25, 100))

            self._pyttsx3_engine.say(text)
            self._pyttsx3_engine.runAndWait()

            # Restore English voice and rate
            self._pyttsx3_engine.setProperty("voice", original_voice)
            self._pyttsx3_engine.setProperty("rate", self._rate)

        except Exception as e:
            log.warning(f"espeak Hindi failed: {e}")
            self._speak_english(text)

    def _speak_hindi_gtts(self, text: str) -> bool:
        """Speak Hindi text using gTTS + pygame (requires internet).

        Returns True if speech was successful, False otherwise.
        """
        if not self._pygame_initialized:
            self._init_pygame()

        if not self._pygame_initialized:
            log.warning(f"pygame unavailable, cannot speak Hindi: {text}")
            return False

        try:
            from gtts import gTTS
            import pygame

            log.debug(f"Speaking (HI-gTTS): {text}")

            filename = os.path.join(self._temp_dir, f"hi_{uuid.uuid4().hex[:8]}.mp3")
            tts = gTTS(text=text, lang=self._gtts_lang)
            tts.save(filename)

            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                time.sleep(0.1)

            pygame.mixer.music.unload()
            try:
                os.remove(filename)
            except OSError:
                pass

            return True

        except ImportError:
            log.error("gTTS not installed — Hindi TTS unavailable")
            self._speak_english(text)
        except Exception as e:
            log.error(f"Hindi gTTS error: {e}")
            return False

    def _speak_with_fresh_engine(self, text: str):
        """
        Speak using a freshly created pyttsx3 engine.
        Used only on Windows to work around the SAPI5 daemon thread bug.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)
            log.debug(f"Speaking (fresh engine): {text}")
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            log.error(f"pyttsx3 fresh engine error: {e}")

    def _cleanup_temp_files(self):
        """Remove any leftover temp audio files."""
        if os.path.exists(self._temp_dir):
            for f in os.listdir(self._temp_dir):
                try:
                    os.remove(os.path.join(self._temp_dir, f))
                except OSError:
                    pass
