import json
import unittest

from language_video_automation.config import project_root
from language_video_automation.models import ContentPackRecord
from language_video_automation.renderer import build_asset_timeline


class RendererTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(encoding="utf-8")
        )
        cls.record = ContentPackRecord.from_dict(data)

    def test_short_uses_english_then_german_twice(self):
        asset = self.record.content["shorts"][0]
        timeline = build_asset_timeline(self.record.content, asset, "short")
        lesson_segments = timeline[1:4]
        self.assertEqual(
            [segment.spoken_language for segment in lesson_segments],
            ["English", "German", "German"],
        )
        self.assertEqual(lesson_segments[1].transcript, lesson_segments[2].transcript)

    def test_long_uses_english_then_german_twice_for_each_line(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        turn = asset["dialogue"][0]
        first_line = [
            segment for segment in timeline
            if segment.display_mode == "lesson"
            and segment.transcript in {turn["english"], turn["german"]}
        ]
        self.assertEqual(
            [segment.spoken_language for segment in first_line],
            ["English", "German", "German"],
        )
        self.assertEqual(first_line[1].transcript, first_line[2].transcript)

    def test_long_has_tutor_guidance_and_short_practice_pauses(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        tutor_segments = [segment for segment in timeline if "TUTOR" in segment.eyebrow]
        self.assertGreaterEqual(len(tutor_segments), len(asset["dialogue"]) * 3)
        repeat_segments = [
            segment for segment in timeline
            if segment.display_mode == "lesson" and segment.cue_text == "REPEAT ALOUD"
        ]
        self.assertTrue(repeat_segments)
        self.assertTrue(all(segment.pause_seconds <= 5.0 for segment in repeat_segments))

    def test_long_ends_with_one_german_only_full_conversation(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        conversation = [
            segment for segment in timeline if segment.display_mode == "conversation"
        ]
        self.assertEqual(len(conversation), len(asset["dialogue"]))
        self.assertEqual(
            [segment.transcript for segment in conversation],
            [turn["german"] for turn in asset["dialogue"]],
        )
        self.assertTrue(all(segment.spoken_language == "German" for segment in conversation))
        self.assertEqual(timeline[-len(conversation):], conversation)

    def test_lesson_view_keeps_english_above_german_data_together(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        first_line = timeline[1:7]
        self.assertTrue(all(segment.display_mode == "lesson" for segment in first_line))
        self.assertTrue(all(segment.english_text == asset["dialogue"][0]["english"] for segment in first_line))
        self.assertTrue(all(segment.german_text == asset["dialogue"][0]["german"] for segment in first_line))


if __name__ == "__main__":
    unittest.main()
