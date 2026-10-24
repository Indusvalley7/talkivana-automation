import unittest

from language_video_automation.config import load_config
from language_video_automation.pipeline import build_youtube_description


class DescriptionTests(unittest.TestCase):
    def test_long_description_uses_heading_for_both_approved_placeholders(self):
        description = build_youtube_description(
            kind="long",
            content={"title": "Booking a Doctor's Appointment"},
            config=load_config(),
            pack_id="pack-1",
            asset_id="long-1",
        )
        topic = "booking a doctor's appointment"
        self.assertIn(f"we’ll practise **{topic}**", description)
        self.assertIn(f"Useful phrases for **{topic}**", description)
        self.assertTrue(description.endswith("#SpeakingPractice #Talkivana"))
        self.assertNotIn("Pack ID:", description)

    def test_short_description_keeps_existing_format(self):
        description = build_youtube_description(
            kind="short",
            content={"title": "Words", "description": "Learn these words."},
            config=load_config(),
            pack_id="pack-1",
            asset_id="short-1",
        )
        self.assertIn("Learn these words.", description)
        self.assertIn("Pack ID: pack-1", description)
        self.assertIn("Asset ID: short-1", description)


if __name__ == "__main__":
    unittest.main()
