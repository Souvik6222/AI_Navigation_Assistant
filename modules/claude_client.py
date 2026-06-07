# ============================================================
# modules/claude_client.py — Groq API wrapper for scene description
# ============================================================

import json
import os
import threading
import time

from utils.logger import get_logger

log = get_logger("groq")

# ---- Production-ready prompts (adapted from PRD Section 7) ----

SYSTEM_PROMPT = """You are an AI navigation assistant for visually impaired users. You receive camera frames and object detection data from a real-time vision system.

Your role is to generate clear, concise, and accurate voice instructions to help the user navigate safely.

Rules:
- Only describe objects CONFIRMED by the detection system — do NOT hallucinate
- Prioritize by proximity: closest objects mentioned first
- Keep responses SHORT — maximum 2 sentences
- Use simple, direct, everyday language
- Respond in user's preferred language: {language}
- NEVER guess or assume objects not present in detection data
- If detection data is empty or uncertain, say: "Path seems clear"
- For urgent obstacles (< 1m), start with "STOP" or "RUKO" (Hindi)

Detection input format:
{{ "objects": [ {{ "label": "chair", "distance_m": 1.2, "direction": "LEFT", "confidence": 0.91 }} ] }}

Output: Plain text voice instruction ONLY. No JSON, no markdown, no explanation."""

SCENE_DESCRIPTION_PROMPT = """You are a scene describer for a visually impaired navigation assistant.

You will receive:
1. A camera frame image (annotated with bounding boxes)
2. A JSON list of all detected objects with distances and directions

Your task: Generate a natural, helpful 2-3 sentence description of the user's current environment.

Rules:
- Mention the most important obstacles FIRST (closest, most dangerous)
- Include approximate distances in meters
- Explicitly mention if the path directly ahead is clear or blocked
- Use conversational, friendly language — not technical terms
- Language: {language}
- Do NOT mention confidence scores, model names, or bounding boxes
- Do NOT say "I can see" or "The image shows" — speak directly to the user

Detections: {detections_json}

Output: Natural language scene description. No markdown, no bullet points."""

HINDI_TRANSLATION_PROMPT = """Translate the following English navigation instruction into natural, conversational Hindi (Devanagari script).

Rules:
- Maximum 1 sentence — keep it SHORT
- Use simple everyday Hindi that any person can understand
- Preserve urgency: if the original sounds urgent, your Hindi must also sound urgent
- Do NOT add extra words, explanations, or context
- Do NOT transliterate (write in Devanagari script, not Roman script)
- If the instruction contains a direction like "left" → "बायीं", "right" → "दायीं", "ahead" → "आगे"

English instruction to translate: {english_instruction}

Output: Hindi translation ONLY. Nothing else."""

EMERGENCY_STOP_PROMPT = """CRITICAL SAFETY SITUATION: An obstacle has been detected extremely close to the user.

Distance: {distance} meters
Object: {object_label}
Direction: {direction}
Language: {language}

Generate an URGENT stop instruction.

Requirements:
- MUST convey immediate danger clearly
- MUST instruct the user to STOP immediately
- Maximum 6 words
- Language: {language}
- English examples: "STOP! Wall directly ahead!", "DANGER! Person very close!"
- Hindi examples: "रुको! दीवार सामने है!", "खतरा! कोई बहुत पास है!"

Output: Urgent instruction ONLY. No explanation."""

MULTI_OBJECT_PROMPT = """Multiple objects have been detected simultaneously. Generate ONE combined voice instruction covering the 2 most dangerous objects.

Priority rules (apply in order):
1. Objects closer than 1m get HIGHEST priority regardless of direction
2. CENTER direction > LEFT/RIGHT if same distance
3. Objects labeled "person" or "car" get +0.5 priority boost (dynamic obstacles)
4. Maximum 2 objects mentioned in a single instruction

Detections JSON: {detections_json}
Language: {language}

Output: Single voice instruction, maximum 12 words. Plain text only."""

STARTUP_PROMPT = """The AI Navigation Assistant has just started up successfully.

Language mode: {language}
Hardware: Laptop + Webcam

Generate a short, friendly startup greeting that:
- Confirms the system is now active and monitoring
- Sounds warm and confidence-inspiring (not robotic)
- Mentions the language being used
- Maximum 15 words
- English example: "Navigation assistant is ready. I will guide you in English."
- Hindi example: "नेविगेशन असिस्टेंट तैयार है। मैं आपको हिंदी में मार्गदर्शन करूँगा।"

Output: Startup greeting ONLY."""

DANGER_LEVEL_PROMPT = """Assess the overall danger level of the current scene for a visually impaired person and recommend immediate action.

Detections: {detections_json}
User speed estimate: {user_speed}  (stationary / slow / fast)
Language: {language}

Danger levels:
- SAFE: No objects within 2m, path clear
- CAUTION: Objects 1-2m away, no immediate threat
- WARNING: Object within 1m, user should slow down
- DANGER: Object within 0.8m, user must stop

Output (2 parts, plain text):
1. Danger level: [SAFE / CAUTION / WARNING / DANGER]
2. Recommended voice instruction in {language} (max 8 words)"""


class ClaudeClient:
    """
    Groq API wrapper for non-critical scene description.

    IMPORTANT: This is NOT used in the real-time navigation path.
    It runs asynchronously in a separate thread. Responses are
    delivered to the VoiceEngine when ready (1-3s delay acceptable).

    Triggered by:
        - Keyboard press 'D'
        - Auto-timer every 30 seconds
    """

    def __init__(self, config: dict):
        """
        Initialize Groq client.

        Args:
            config: Full config dict. Uses 'groq' section.
        """
        groq_config = config.get("groq", {})
        self.model = groq_config.get("model", "meta-llama/llama-4-scout-17b-16e-instruct")
        self.max_tokens = groq_config.get("max_tokens", 300)
        self.temperature = groq_config.get("temperature", 0.3)
        self.auto_interval = groq_config.get("auto_trigger_interval_seconds", 30)
        self.enabled = groq_config.get("enabled", True)

        self._client = None
        self._last_trigger_time = 0.0
        self._voice_engine = None
        self._status = "idle"

        # Load API key
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        api_key = os.environ.get("GROQ_API_KEY", "")

        if not api_key or api_key == "your_api_key_here":
            log.warning("GROQ_API_KEY not set — Groq features disabled")
            self.enabled = False
        else:
            try:
                from groq import Groq
                self._client = Groq(api_key=api_key)
                log.info(f"Groq client initialized — model={self.model}")
            except ImportError:
                log.error("groq package not installed — run: pip install groq")
                self.enabled = False
            except Exception as e:
                log.error(f"Failed to initialize Groq client: {e}")
                self.enabled = False

    def set_voice_engine(self, voice_engine):
        """Set reference to VoiceEngine for delivering responses via TTS."""
        self._voice_engine = voice_engine

    def get_status(self) -> str:
        """Get current Groq API status for status bar."""
        return self._status

    def describe_scene_async(
        self,
        frame_base64: str,
        detections: list[dict],
        language: str = "en",
    ):
        """
        Trigger an async scene description via Groq API.

        Runs in a separate thread. Result is sent to VoiceEngine when ready.

        Args:
            frame_base64: Base64-encoded JPEG of annotated frame.
            detections: List of detection dicts.
            language: "en" or "hi".
        """
        if not self.enabled:
            return

        self._status = "thinking..."
        thread = threading.Thread(
            target=self._describe_scene_worker,
            args=(frame_base64, detections, language),
            daemon=True,
            name="GroqWorker",
        )
        thread.start()

    def _describe_scene_worker(
        self,
        frame_base64: str,
        detections: list[dict],
        language: str,
    ):
        """Worker thread for Groq API call."""
        try:
            # Build detections JSON for prompt
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

            lang_name = "Hindi" if language == "hi" else "English"

            # Build the prompt
            user_prompt = SCENE_DESCRIPTION_PROMPT.format(
                language=lang_name,
                detections_json=det_json,
            )

            system_prompt = SYSTEM_PROMPT.format(language=lang_name)

            # Make API call with image (Groq uses OpenAI-compatible format)
            log.info("Sending scene description request to Groq...")

            message = self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{frame_base64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": user_prompt,
                            },
                        ],
                    },
                ],
            )

            response_text = message.choices[0].message.content.strip()
            log.info(f"Groq response: {response_text}")
            self._status = "done"

            # Deliver via TTS
            if self._voice_engine:
                self._voice_engine.speak(response_text, language)

        except Exception as e:
            log.error(f"Groq API error: {e}")
            self._status = "error"

            # Speak fallback
            if self._voice_engine:
                if language == "hi":
                    self._voice_engine.speak("Scene description uplabdh nahi hai.", "hi")
                else:
                    self._voice_engine.speak("Scene description unavailable.", "en")

    def should_auto_trigger(self) -> bool:
        """
        Check if enough time has elapsed for an auto scene description.

        Returns:
            True if auto_interval seconds have passed since last trigger.
        """
        if not self.enabled:
            return False
        return (time.time() - self._last_trigger_time) >= self.auto_interval

    def mark_triggered(self):
        """Record that a scene description was just triggered."""
        self._last_trigger_time = time.time()

    def get_startup_greeting(self, language: str = "en") -> str | None:
        """
        Get a startup greeting from Groq (synchronous, one-time use).

        Falls back to hardcoded greeting if Groq is unavailable.

        Args:
            language: "en" or "hi".

        Returns:
            Startup greeting string.
        """
        if not self.enabled or self._client is None:
            # Hardcoded fallback
            if language == "hi":
                return "Navigation assistant taiyaar hai. Hindi mein maargadarshan milega."
            return "Navigation assistant is ready. I will guide you in English."

        try:
            lang_name = "Hindi" if language == "hi" else "English"
            prompt = STARTUP_PROMPT.format(language=lang_name)
            system = SYSTEM_PROMPT.format(language=lang_name)

            message = self._client.chat.completions.create(
                model=self.model,
                max_tokens=50,
                temperature=0.5,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            return message.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"Startup greeting failed: {e}")
            if language == "hi":
                return "Navigation assistant taiyaar hai. Hindi mein maargadarshan milega."
            return "Navigation assistant is ready. I will guide you in English."
