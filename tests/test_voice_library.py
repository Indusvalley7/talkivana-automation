import hashlib
import json
import unittest

from language_video_automation.config import project_root


class VoiceLibraryTests(unittest.TestCase):
    def test_approved_reference_files_match_manifest(self):
        root = project_root()
        manifest = json.loads(
            (root / "voice_library" / "VOICE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(manifest["voices"]), {"A", "B"})
        for voice in manifest["voices"].values():
            path = root / voice["file"]
            self.assertTrue(path.is_file(), path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, voice["sha256"])
            self.assertTrue(voice["synthetic"])


if __name__ == "__main__":
    unittest.main()
