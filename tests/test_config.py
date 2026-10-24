import copy
import json
import tempfile
import unittest
from pathlib import Path

from language_video_automation.config import ConfigurationError, load_config, project_root, validate_production_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((project_root() / "config" / "channel.json").read_text(encoding="utf-8"))

    def write(self, data):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "channel.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return load_config(path)

    def test_checked_in_configuration_is_ready_for_manual_private_production(self):
        config = load_config()
        self.assertTrue(config.enabled)
        validate_production_config(config)

    def test_config_can_become_production_ready(self):
        data = copy.deepcopy(self.base)
        data["system"]["enabled"] = True
        data["playlists"][0]["youtube_playlist_id"] = "PL_TEST_GERMAN"
        data["models"]["tts_settings"]["conversation_voice_references"] = {
            "A": "voice_library/speaker-a-female.wav",
            "B": "voice_library/speaker-b-male.wav",
        }
        config = self.write(data)
        validate_production_config(config)

    def test_production_rejects_missing_or_shared_character_voices(self):
        data = copy.deepcopy(self.base)
        data["system"]["enabled"] = True
        data["playlists"][0]["youtube_playlist_id"] = "PL_TEST_GERMAN"
        data["models"]["tts_settings"]["conversation_voice_references"] = {
            "A": "",
            "B": "",
        }
        with self.assertRaises(ConfigurationError):
            validate_production_config(self.write(data))
        data["models"]["tts_settings"]["conversation_voice_references"] = {
            "A": "voice_library/shared.wav",
            "B": "voice_library/shared.wav",
        }
        with self.assertRaises(ConfigurationError):
            validate_production_config(self.write(data))

    def test_production_requires_approved_german_narration_reference(self):
        data = copy.deepcopy(self.base)
        data["models"]["tts_settings"]["german_reference_audio"] = ""
        with self.assertRaises(ConfigurationError):
            validate_production_config(self.write(data))

    def test_nonseparated_slots_are_rejected(self):
        data = copy.deepcopy(self.base)
        data["youtube"]["seed_publish_slots_local"] = ["08:00", "08:30", "18:00", "22:00"]
        with self.assertRaises(ConfigurationError):
            self.write(data)

    def test_long_description_template_requires_both_dynamic_fields(self):
        data = copy.deepcopy(self.base)
        data["youtube"]["long_description_template"] = "Only {lesson_topic} is present."
        with self.assertRaises(ConfigurationError):
            self.write(data)

    def test_unknown_dry_run_asset_is_rejected(self):
        data = copy.deepcopy(self.base)
        data["system"]["dry_run_asset_id"] = "long-99"
        with self.assertRaises(ConfigurationError):
            self.write(data)

    def test_private_production_selects_all_four_assets(self):
        from language_video_automation.pipeline import _production_asset_ids

        config = load_config()
        self.assertEqual(
            _production_asset_ids(config),
            ("short-1", "short-2", "long-1", "long-2"),
        )


if __name__ == "__main__":
    unittest.main()
