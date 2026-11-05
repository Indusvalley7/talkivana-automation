from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from language_video_automation.gemini import GeminiClient, GeminiError, _status_code


class _ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _Interactions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(output_text=json.dumps(outcome))


def _client(outcomes: list[object]) -> tuple[GeminiClient, _Interactions]:
    interactions = _Interactions(outcomes)
    client = GeminiClient.__new__(GeminiClient)
    client._client = SimpleNamespace(interactions=interactions)
    client._max_requests = 8
    client._requests = 0
    client._min_interval_seconds = 0.0
    client._last_request_at = 0.0
    client._request_timeout_seconds = 123.0
    client._fallback_models = ("fallback-model", "last-model")
    return client, interactions


class GeminiClientTests(unittest.TestCase):
    @patch("language_video_automation.gemini.time.sleep")
    def test_transient_error_retries_with_timeout(self, sleep) -> None:
        client, interactions = _client([
            _ProviderError("temporarily unavailable", 503),
            {"ok": True},
        ])

        value = client.generate_json(
            model="test-model",
            prompt="test prompt",
            schema={"type": "object"},
            operation="test stage",
        )

        self.assertEqual(value, {"ok": True})
        self.assertEqual(len(interactions.calls), 2)
        self.assertEqual(
            [call["model"] for call in interactions.calls],
            ["test-model", "fallback-model"],
        )
        self.assertEqual(interactions.calls[0]["timeout"], 123.0)
        sleep.assert_called_once_with(10)

    @patch("language_video_automation.gemini.time.sleep")
    def test_auth_error_does_not_retry(self, sleep) -> None:
        client, interactions = _client([_ProviderError("invalid API key", 401)])

        with self.assertRaisesRegex(GeminiError, "after 1 model attempt"):
            client.generate_json(
                model="test-model",
                prompt="test prompt",
                schema={"type": "object"},
                operation="test stage",
            )

        self.assertEqual(len(interactions.calls), 1)
        sleep.assert_not_called()

    def test_status_code_reads_chained_provider_error(self) -> None:
        outer = RuntimeError("wrapper")
        outer.__cause__ = _ProviderError("quota", 429)
        self.assertEqual(_status_code(outer), 429)


if __name__ == "__main__":
    unittest.main()
