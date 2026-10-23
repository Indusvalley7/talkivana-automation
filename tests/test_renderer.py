import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from language_video_automation.config import project_root
from language_video_automation.models import ContentPackRecord
from language_video_automation.renderer import (
    TestToneSpeechProvider,
    build_asset_timeline,
    prepare_asset_voice_stage,
)


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

    def test_long_opening_is_broken_into_shorter_tutor_beats(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        intro = [segment for segment in timeline if segment.display_mode == "intro"]
        self.assertEqual(len(intro), 3)
        self.assertEqual([segment.pause_seconds for segment in intro], [0.9, 0.8, 1.5])
        self.assertTrue(all(segment.spoken_language == "English" for segment in intro))
        self.assertTrue(all(len(segment.transcript.split()) <= 20 for segment in intro))

    def test_pronunciation_guide_is_visible_but_never_spoken(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        pronunciation_values = {turn["pronunciation"] for turn in asset["dialogue"]}
        spoken = [segment.transcript for segment in timeline]
        self.assertFalse(any(value in transcript for value in pronunciation_values for transcript in spoken))
        lesson_segments = [segment for segment in timeline if segment.display_mode == "lesson"]
        self.assertTrue(all(segment.pronunciation for segment in lesson_segments))

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
        expected_voice_ids = [f"speaker:{turn['speaker']}" for turn in asset["dialogue"]]
        self.assertEqual([segment.voice_id for segment in conversation], expected_voice_ids)
        self.assertGreaterEqual(len(set(expected_voice_ids)), 2)
        self.assertEqual(timeline[-len(conversation):], conversation)

    def test_lesson_view_keeps_english_above_german_data_together(self):
        asset = self.record.content["long_videos"][0]
        timeline = build_asset_timeline(self.record.content, asset, "long")
        first_turn = asset["dialogue"][0]
        first_line = [
            segment for segment in timeline
            if segment.display_mode == "lesson"
            and segment.english_text == first_turn["english"]
            and segment.german_text == first_turn["german"]
        ]
        self.assertEqual(len(first_line), 6)
        self.assertTrue(all(segment.display_mode == "lesson" for segment in first_line))
        self.assertTrue(all(segment.english_text == asset["dialogue"][0]["english"] for segment in first_line))
        self.assertTrue(all(segment.german_text == asset["dialogue"][0]["german"] for segment in first_line))

    def test_voice_job_writes_a_portable_stage_manifest(self):
        asset = self.record.content["shorts"][0]

        def wav_duration(path):
            with wave.open(str(path), "rb") as stream:
                return stream.getnframes() / stream.getframerate()

        with tempfile.TemporaryDirectory() as temporary:
            stage_dir = Path(temporary)
            with (
                patch("language_video_automation.renderer._require_ffmpeg"),
                patch(
                    "language_video_automation.renderer._probe_duration",
                    side_effect=wav_duration,
                ),
            ):
                manifest_path = prepare_asset_voice_stage(
                    record=self.record,
                    asset=asset,
                    kind="short",
                    config=json.loads(
                        (project_root() / "config" / "channel.json").read_text(encoding="utf-8")
                    ),
                    speech=TestToneSpeechProvider(),
                    stage_dir=stage_dir,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["asset_id"], "short-1")
            self.assertTrue(manifest["segments"])
            self.assertTrue(
                all((stage_dir / item["audio_file"]).is_file() for item in manifest["segments"])
            )


if __name__ == "__main__":
    unittest.main()
