import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from language_video_automation.config import project_root
from language_video_automation.models import ContentPackRecord
from language_video_automation.thumbnails import (
    DESIGN_VERSION,
    ThumbnailError,
    build_thumbnail_plan,
    load_design_skill,
    render_youtube_thumbnail,
)


class ThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )
        cls.record = ContentPackRecord.from_dict(data)

    def test_checked_in_skill_profile_is_loaded(self):
        text = load_design_skill(root=project_root())
        self.assertIn("name: youtube-thumbnail-design", text)
        self.assertEqual(DESIGN_VERSION, "talkivana-thumbnail-v1")

    def test_skill_profile_is_mandatory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ThumbnailError):
                load_design_skill(root=Path(temporary))

    def test_each_asset_gets_a_valid_distinct_content_specific_thumbnail(self):
        assets = [
            *(('short', item) for item in self.record.content["shorts"]),
            *(('long', item) for item in self.record.content["long_videos"]),
        ]
        hashes = set()
        headlines = set()
        palettes = set()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, asset in assets:
                output = root / f"{asset['asset_id']}.jpg"
                plan = render_youtube_thumbnail(
                    asset=asset,
                    kind=kind,
                    pack_id=self.record.pack_id,
                    output_path=output,
                    root=project_root(),
                )
                expected = (1080, 1920) if kind == "short" else (1280, 720)
                with Image.open(output) as image:
                    self.assertEqual(image.size, expected)
                    self.assertEqual(image.format, "JPEG")
                self.assertLess(output.stat().st_size, 2 * 1024 * 1024)
                self.assertLessEqual(len(plan.headline.split()), 6)
                self.assertNotIn("GERMAN IN 10 DAYS", plan.headline)
                hashes.add(hashlib.sha256(output.read_bytes()).hexdigest())
                headlines.add(plan.headline)
                palettes.add(plan.palette_name)
        self.assertEqual(len(hashes), 4)
        self.assertEqual(len(headlines), 4)
        self.assertEqual(len(palettes), 4)

    def test_copy_is_derived_from_the_lesson_situation(self):
        plan = build_thumbnail_plan(
            asset={
                "asset_id": "long-1",
                "title": "Booking a Doctor's Appointment",
                "scenario": "A patient calls a clinic.",
                "focus_vocabulary": [{"german": "Termin"}],
            },
            kind="long",
            pack_id="pack-1",
        )
        self.assertEqual(plan.headline, "BOOK A DOCTOR")
        self.assertEqual(plan.visual_key, "calendar")


if __name__ == "__main__":
    unittest.main()
