import copy
import json
import unittest
from datetime import date

from language_video_automation.config import load_config, project_root
from language_video_automation.generator import ContentPackGenerator
from language_video_automation.models import _german_vocabulary_used


class _FakeGeminiClient:
    def __init__(self, pack):
        self.pack = pack
        self.calls = 0
        self.prompts = []

    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls == 1:
            return copy.deepcopy(self.pack)
        return {
            "approved": True,
            "problems": ["Restored configuration-owned metadata."],
            "corrected_pack": copy.deepcopy(self.pack),
        }


class _RepairingGeminiClient(_FakeGeminiClient):
    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls == 1:
            return copy.deepcopy(self.pack)
        if self.calls == 2:
            invalid = copy.deepcopy(self.pack)
            for turn in invalid["long_videos"][1]["dialogue"]:
                turn["german"] = turn["german"].replace("Kaffee", "Tee")
            return {
                "approved": False,
                "problems": [],
                "corrected_pack": invalid,
            }
        return {
            "approved": True,
            "problems": ["Restored the exact linked vocabulary in natural context."],
            "corrected_pack": copy.deepcopy(self.pack),
        }


class GeneratorTests(unittest.TestCase):
    def test_natural_german_inflections_and_separable_verbs_count_as_linked_vocabulary(self):
        self.assertTrue(_german_vocabulary_used("frisch", "Wir kaufen frische Brötchen."))
        self.assertTrue(_german_vocabulary_used("abfahren", "Der Zug fährt um acht Uhr ab."))
        self.assertFalse(_german_vocabulary_used("abfahren", "Der Zug kommt um acht Uhr an."))

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
        self.assertEqual(client.calls, 3)

    def test_tutor_skill_profile_is_applied_to_generation_and_review(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _FakeGeminiClient(fixture)
        ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 25),
        )

        self.assertEqual(len(client.prompts), 3)
        for prompt in client.prompts[:2]:
            self.assertIn("Talkivana Language Learning Companion Profile", prompt)
            self.assertIn("complete opening-to-resolution arc", prompt)
            self.assertIn("Do not mix `du` and `Sie`", prompt)
        self.assertIn("spaced-repetition recycling", client.prompts[0])
        self.assertIn("read the German dialogue from first to last", client.prompts[1])
        self.assertIn("final adversarial Talkivana conversation auditor", client.prompts[2])
        self.assertIn("specific role would naturally say", client.prompts[2])

    def test_validation_failure_gets_one_bounded_tutor_repair(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _RepairingGeminiClient(fixture)
        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 25),
        )

        self.assertEqual(client.calls, 4)
        self.assertIn("does not use linked vocabulary word family", client.prompts[2])
        self.assertIn("recognisable natural word-family form", client.prompts[2])
        self.assertIn("final adversarial Talkivana conversation auditor", client.prompts[3])
        self.assertTrue(
            any("Deterministic validation repair" in item for item in record.qa_problems)
        )


if __name__ == "__main__":
    unittest.main()
