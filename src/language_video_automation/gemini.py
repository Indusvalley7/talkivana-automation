from __future__ import annotations

import base64
import json
import os
import re
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
        request_timeout_seconds: float = 180,
        fallback_models: tuple[str, ...] | list[str] = (),
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
        if request_timeout_seconds <= 0:
            raise GeminiError("Gemini request timeout must be greater than zero.")
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._fallback_models = tuple(
            dict.fromkeys(str(item).strip() for item in fallback_models if str(item).strip())
        )

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

    def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict[str, Any],
        operation: str = "JSON generation",
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        attempt_models = tuple(dict.fromkeys((model, *self._fallback_models)))[:3]
        for attempt, attempt_model in enumerate(attempt_models):
            self._claim_request()
            started_at = time.monotonic()
            print(
                f"Gemini stage '{operation}': attempt {attempt + 1}/{len(attempt_models)} "
                f"with {attempt_model} "
                f"(guard request {self._requests}/{self._max_requests}).",
                flush=True,
            )
            try:
                interaction = self._client.interactions.create(
                    model=attempt_model,
                    input=prompt,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema,
                    },
                    timeout=self._request_timeout_seconds,
                )
                text = interaction.output_text
                if not text:
                    raise GeminiError("Gemini returned no JSON text.")
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise GeminiError("Gemini JSON response was not an object.")
                print(
                    f"Gemini stage '{operation}' completed with {attempt_model} in "
                    f"{time.monotonic() - started_at:.1f}s.",
                    flush=True,
                )
                return value
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # provider exceptions change between SDK releases
                last_error = exc
                status_code = _status_code(exc)
                retryable = status_code not in {400, 401, 403, 404}
                error_summary = _safe_error_summary(exc)
                print(
                    f"Gemini stage '{operation}' failed with {attempt_model} on attempt "
                    f"{attempt + 1}/{len(attempt_models)} "
                    f"after {time.monotonic() - started_at:.1f}s: {error_summary}",
                    flush=True,
                )
                if attempt + 1 < len(attempt_models) and retryable:
                    delay = (10, 30)[attempt]
                    print(
                        f"Retrying Gemini stage '{operation}' with the next configured "
                        f"free-tier model in {delay}s.",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                break
        raise GeminiError(
            f"Gemini stage '{operation}' failed after {attempt + 1} model attempt(s): "
            f"{_safe_error_summary(last_error)}"
        ) from last_error

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
                    timeout=self._request_timeout_seconds,
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


def _status_code(exc: Exception) -> int | None:
    """Extract a provider HTTP status without depending on one SDK exception class."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attribute in ("status_code", "code"):
            value = getattr(current, attribute, None)
            if callable(value):
                continue
            match = re.search(r"\b([1-5][0-9]{2})\b", str(value or ""))
            if match:
                return int(match.group(1))
        current = current.__cause__ or current.__context__
    return None


def _safe_error_summary(exc: Exception | None) -> str:
    """Keep Actions diagnostics useful without dumping prompts or credentials."""
    if exc is None:
        return "unknown provider error"
    detail = " ".join(str(exc).split())
    if len(detail) > 500:
        detail = detail[:497] + "..."
    return f"{type(exc).__name__}: {detail or 'no error message'}"
