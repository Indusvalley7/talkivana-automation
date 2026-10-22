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

    def test_default_configuration_is_safely_disabled(self):
        config = load_config()
        self.assertFalse(config.enabled)
        with self.assertRaises(ConfigurationError):
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

    def test_nonseparated_slots_are_rejected(self):
        data = copy.deepcopy(self.base)
        data["youtube"]["seed_publish_slots_local"] = ["08:00", "08:30", "18:00", "22:00"]
        with self.assertRaises(ConfigurationError):
            self.write(data)


if __name__ == "__main__":
    unittest.main()
