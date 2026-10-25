import unittest

from language_video_automation.config import load_config
from language_video_automation.pipeline import _visual_bold, build_youtube_description


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
        bold_topic = _visual_bold(topic)
        self.assertIn(f"we’ll practise {bold_topic}", description)
        self.assertIn(f"Useful phrases for {bold_topic}", description)
        self.assertIn(_visual_bold("Talkivana"), description)
        self.assertNotIn("**", description)
        self.assertTrue(description.endswith("#SpeakingPractice #Talkivana"))
        self.assertNotIn("Pack ID:", description)

    def test_short_description_uses_two_sentences_and_hashtags_without_internal_metadata(self):
        description = build_youtube_description(
            kind="short",
            content={
                "title": "Direction Words",
                "description": "Essential German vocabulary for asking for and understanding directions.",
            },
            config=load_config(),
            pack_id="pack-1",
            asset_id="short-1",
        )
        self.assertEqual(
            description,
            "Essential German vocabulary for asking for and understanding directions.\n\n"
            "Talkivana — Real Conversations.\n\n"
            "#LearnGerman #GermanForBeginners #GermanVocabulary #Talkivana",
        )
        self.assertNotIn("synthetic narration", description)
        self.assertNotIn("Pack ID:", description)
        self.assertNotIn("Asset ID:", description)


if __name__ == "__main__":
    unittest.main()
