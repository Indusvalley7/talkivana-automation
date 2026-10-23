import copy
import json
import unittest
from datetime import date

from language_video_automation.config import load_config, project_root
from language_video_automation.generator import ContentPackGenerator


class _FakeGeminiClient:
    def __init__(self, pack):
        self.pack = pack
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return copy.deepcopy(self.pack)
        return {
            "approved": True,
            "problems": ["Restored configuration-owned metadata."],
            "corrected_pack": copy.deepcopy(self.pack),
        }


class GeneratorTests(unittest.TestCase):
    def test_configuration_owned_metadata_is_normalized_before_approval(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        fixture["source_language"] = "English (international)"
        fixture["target_language"] = "Deutsch"
        fixture["language_variety"] = "Hochdeutsch"
        fixture["level"] = "A1"
        config = load_config()
        client = _FakeGeminiClient(fixture)
        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 23),
        )
        self.assertEqual(record.content["source_language"], "English")
        self.assertEqual(record.content["target_language"], "German")
        self.assertEqual(
            record.content["language_variety"],
            "Standard German used in Germany; no dialects",
        )
        self.assertEqual(record.content["level"], "absolute beginner")
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
