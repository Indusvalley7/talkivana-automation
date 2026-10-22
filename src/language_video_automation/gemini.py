from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    """Small guarded wrapper around the current Gemini Interactions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_requests: int = 40,
        min_interval_seconds: float = 0,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise GeminiError("GEMINI_API_KEY is missing.")
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiError("google-genai is not installed; install requirements.txt.") from exc
        self._client = genai.Client(api_key=key)
        self._max_requests = max_requests
        self._requests = 0
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0

    @property
    def request_count(self) -> int:
        return self._requests

    def _claim_request(self) -> None:
        if self._requests >= self._max_requests:
            raise GeminiError(f"Gemini request guard reached ({self._max_requests}).")
        wait = self._min_interval_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._requests += 1
        self._last_request_at = time.monotonic()

    def generate_json(self, *, model: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            self._claim_request()
            try:
                interaction = self._client.interactions.create(
                    model=model,
                    input=prompt,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema,
                    },
                )
                text = interaction.output_text
                if not text:
                    raise GeminiError("Gemini returned no JSON text.")
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise GeminiError("Gemini JSON response was not an object.")
                return value
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # provider exceptions change between SDK releases
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise GeminiError(f"Gemini JSON generation failed after retries: {last_error}") from last_error

    def synthesize_wav(
        self,
        *,
        model: str,
        voice: str,
        transcript: str,
        language: str,
        output_path: Path,
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            self._claim_request()
            try:
                interaction = self._client.interactions.create(
                    model=model,
                    input=[
                        {
                            "type": "user_input",
                            "content": [
                                {
                                    "type": "text",
                                    "text": transcript,
                                    "annotations": [
                                        {
                                            "type": "speech_metadata",
                                            "style": (
                                                f"Sound like a bright, cheerful and encouraging language tutor. "
                                                f"Use natural {language} pronunciation, friendly varied intonation, "
                                                "and a clear conversational pace. Smile through the delivery without "
                                                "becoming theatrical. Never sound flat, robotic, sleepy, or rushed. "
                                                "Recite the supplied wording exactly."
                                            ),
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    response_format={"type": "audio", "mime_type": "audio/wav"},
                    generation_config={"speech_config": [{"voice": voice}]},
                )
                audio = interaction.output_audio
                if audio is None or not getattr(audio, "data", None):
                    raise GeminiError("Gemini returned no audio data.")
                data = audio.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if not isinstance(data, (bytes, bytearray)):
                    raise GeminiError("Gemini returned an unknown audio representation.")
                if not bytes(data).startswith(b"RIFF"):
                    raise GeminiError("Gemini TTS response was not a WAV file.")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(bytes(data))
                return
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise GeminiError(f"Gemini TTS failed after retries: {last_error}") from last_error
