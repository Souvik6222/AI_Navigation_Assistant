# ============================================================
# modules/lm_studio_client.py — Local LM Studio LLM wrapper
# ============================================================
# Replaces the cloud Groq/Claude client with a local LLM served
# by LM Studio. LM Studio exposes an OpenAI-compatible REST API
# at http://127.0.0.1:1234/v1 (configurable in config.yaml).
#
# This module ONLY handles TEXT-based tasks (no vision/images).
# The "eye" role is still performed by YOLOv8 + MiDaS.
# ============================================================

import json
import threading
import time

import urllib.request
import urllib.error

from modules.prompts import (
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_HI,
    SCENE_DESCRIPTION_PROMPT_EN,
    SCENE_DESCRIPTION_PROMPT_HI,
    STARTUP_PROMPT_EN,
    STARTUP_PROMPT_HI,
)

from utils.logger import get_logger

log = get_logger("lm_studio")

# ---- Prompts (see prompts.py) ----
# Prompts moved to modules/prompts.py
SYSTEM_PROMPT = """You are a compact navigation assistant AI for visually impaired users.
You receive structured object detection data (JSON) and must output a short voice instruction.

STRICT RULES:
- Respond with a SINGLE plain sentence. No markdown, no JSON, no explanation.
- Maximum 12 words total.
- Prioritize closest object first.
- If nothing is close, say: Path is clear.
- Language: {language}
- For objects under 1 meter: start with STOP (English) or RUKO (Hindi)."""

SCENE_DESCRIPTION_PROMPT = """Describe the user's surroundings in 1-2 short sentences.

Detected objects: {detections_json}

Rules:
- Mention the closest/most dangerous object first with its distance.
- State clearly if the path ahead is blocked or clear.
- Use plain conversational language. No markdown.
- Language: {language}
- Maximum 25 words."""

STARTUP_PROMPT = """Generate a short, friendly startup message for a navigation assistant.
- Language: {language}
- Maximum 12 words.
- Confirm the system is ready and guiding in the given language.
- Example English: Navigation assistant is ready. I will guide you in English.
- Example Hindi: नेविगेशन असिस्टेंट तैयार है। मैं हिंदी में मार्गदर्शन करूँगा।
Output: The greeting sentence ONLY."""

# ---- JSON Schema for Structured Output ----
# LM Studio's "Structured Output" mode enforces this schema,
# so the model always returns { "instruction": "..." }

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": "The voice instruction to speak aloud. Plain text, max 25 words."
        }
    },
    "required": ["instruction"],
    "additionalProperties": False
}


class LMStudioClient:
    """
    Local LLM brain using LM Studio's OpenAI-compatible API.

    Architecture role:
        Eye   → YOLOv8 + MiDaS  (object detection + depth)
        Brain → This class       (language / instruction generation)
        Voice → voice.py         (TTS output)

    The client calls http://127.0.0.1:1234/v1/chat/completions
    (or whichever base_url is set in config.yaml) using plain
    urllib — no openai package required.

    Structured Output mode is used so LM Studio forces the model
    to always return valid JSON matching RESPONSE_SCHEMA.
    """

    def __init__(self, config: dict):
        """
        Initialize LM Studio client.

        Args:
            config: Full config dict. Uses 'lm_studio' section.
        """
        lm_cfg = config.get("lm_studio", {})

        self.base_url: str = lm_cfg.get("base_url", "http://127.0.0.1:1234/v1")
        self.model: str = lm_cfg.get("model", "qwen2.5-coder-3b-instruct-128k")
        self.max_tokens: int = lm_cfg.get("max_tokens", 80)
        self.temperature: float = lm_cfg.get("temperature", 0.2)
        self.timeout: int = lm_cfg.get("timeout_seconds", 8)
        self.auto_interval: float = lm_cfg.get("auto_trigger_interval_seconds", 30)
        self.enabled: bool = lm_cfg.get("enabled", True)
        self.use_structured_output: bool = lm_cfg.get("use_structured_output", True)

        self._voice_engine = None
        self._last_trigger_time: float = 0.0
        self._status: str = "idle"

        # Quick connectivity check on startup
        if self.enabled:
            self._check_server()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_voice_engine(self, voice_engine):
        """Set reference to VoiceEngine for delivering LLM responses via TTS."""
        self._voice_engine = voice_engine

    def get_status(self) -> str:
        """Return current status string for status bar display."""
        return self._status

    def should_auto_trigger(self) -> bool:
        """True if auto_interval seconds have passed since last trigger."""
        if not self.enabled:
            return False
        return (time.time() - self._last_trigger_time) >= self.auto_interval

    def mark_triggered(self):
        """Record that a scene description was just triggered."""
        self._last_trigger_time = time.time()

    def describe_scene_async(
        self,
        frame_base64: str,  # kept for API compatibility — not used (no vision model)
        detections: list,
        language: str = "en",
    ):
        """
        Trigger an async scene description via local LM Studio.

        NOTE: frame_base64 is accepted but ignored — Qwen-2.5-3B is
        a TEXT model only. The detection JSON provides all context.

        Args:
            frame_base64: Ignored (kept for compatibility with main.py).
            detections:   List of detection dicts from the tracker.
            language:     "en" or "hi".
        """
        if not self.enabled:
            return

        self._status = "thinking..."
        thread = threading.Thread(
            target=self._scene_worker,
            args=(detections, language),
            daemon=True,
            name="LMStudioWorker",
        )
        thread.start()

    def get_startup_greeting(self, language: str = "en") -> str:
        """
        Get a startup greeting from the local LLM (synchronous).

        Falls back to a hardcoded greeting if the server is unavailable.

        Args:
            language: "en" or "hi".

        Returns:
            Startup greeting string.
        """
        if not self.enabled:
            return self._fallback_greeting(language)

        try:
            system, scene_prompt, start_prompt = self._get_prompts(language)
            result = self._call_api(system_prompt=system, user_prompt=start_prompt)
            if result:
                log.info(f"LM Studio startup greeting: {result}")
                return result
        except Exception as e:
            log.error(f"Startup greeting failed: {e}")

        return self._fallback_greeting(language)

    # ------------------------------------------------------------------
    # Internal workers
    # ------------------------------------------------------------------

    def _scene_worker(self, detections: list, language: str):
        """Worker thread: builds prompt → calls API → speaks result."""
        try:
            det_json = json.dumps(
                [
                    {
                        "label": d.get("label", "unknown"),
                        "distance_m": round(d.get("distance_m", 0), 1),
                        "direction": d.get("direction", "CENTER"),
                        "confidence": round(d.get("confidence", 0), 2),
                    }
                    for d in detections
                ],
                indent=2,
            )

            system, scene_prompt_template, _ = self._get_prompts(language)
            user_prompt = scene_prompt_template.format(detections_json=det_json)

            log.info("Sending scene description request to LM Studio...")
            result = self._call_api(system_prompt=system, user_prompt=user_prompt)

            self._status = "done"

            if result and self._voice_engine:
                self._voice_engine.speak(result, language)

        except Exception as e:
            log.error(f"LM Studio scene description error: {e}")
            self._status = "error"
            if self._voice_engine:
                fallback = (
                    "Scene description uplabdh nahi hai."
                    if language == "hi"
                    else "Scene description unavailable."
                )
                self._voice_engine.speak(fallback, language)

    @staticmethod
    def _get_prompts(language: str) -> tuple:
        if language == "hi":
            return SYSTEM_PROMPT_HI, SCENE_DESCRIPTION_PROMPT_HI, STARTUP_PROMPT_HI
        return SYSTEM_PROMPT_EN, SCENE_DESCRIPTION_PROMPT_EN, STARTUP_PROMPT_EN

    def _call_api(self, system_prompt: str, user_prompt: str) -> str | None:
        """
        Call LM Studio's /v1/chat/completions endpoint.

        Uses structured output (response_format with JSON schema) if
        use_structured_output is True — this forces the model to always
        return { "instruction": "..." }.

        Returns the extracted instruction string, or None on failure.
        """
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }

        # Attach structured output schema if enabled
        if self.use_structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "navigation_instruction",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            }

        body = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            log.error(f"Cannot reach LM Studio at {url}: {e}")
            self._status = "offline"
            return None

        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"].strip()

            # If structured output is on, content is JSON → extract field
            if self.use_structured_output:
                try:
                    parsed = json.loads(content)
                    return parsed.get("instruction", content)
                except json.JSONDecodeError:
                    # Model returned plain text anyway — use as-is
                    return content
            else:
                return content

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            log.error(f"Unexpected LM Studio response format: {e} | raw={raw[:200]}")
            return None

    def _check_server(self):
        """Ping LM Studio server on startup and log connectivity status."""
        url = f"{self.base_url.rstrip('/')}/models"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id", "?") for m in data.get("data", [])]
                log.info(f"LM Studio connected ✓ | available models: {models}")
                self._status = "ready"
        except Exception as e:
            log.warning(
                f"LM Studio server not reachable at {self.base_url} — "
                f"scene descriptions disabled. Error: {e}"
            )
            self.enabled = False
            self._status = "offline"

    @staticmethod
    def _fallback_greeting(language: str) -> str:
        """Return a hardcoded fallback greeting when LLM is unavailable."""
        if language == "hi":
            return "नेविगेशन असिस्टेंट तैयार है। हिंदी में मार्गदर्शन मिलेगा।"
        return "Navigation assistant is ready. I will guide you in English."
