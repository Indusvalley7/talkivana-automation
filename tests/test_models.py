import json
import unittest

from language_video_automation.config import load_config, project_root
from language_video_automation.github_api import (
    format_issue_body,
    parse_pack_record,
    read_upload_manifest,
    write_upload_manifest,
)
from language_video_automation.models import (
    ContentPackRecord,
    ContentValidationError,
    build_pack_record,
    validate_content_pack,
    validate_record_integrity,
)


class ModelTests(unittest.TestCase):
    def test_provider_schema_avoids_nested_array_state_explosion(self):
        from language_video_automation.models import CONTENT_PACK_JSON_SCHEMA, QA_JSON_SCHEMA

        def walk(value):
            if isinstance(value, dict):
                self.assertNotIn("minItems", value)
                self.assertNotIn("maxItems", value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(CONTENT_PACK_JSON_SCHEMA)
        walk(QA_JSON_SCHEMA)

    @classmethod
    def setUpClass(cls):
        data = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(encoding="utf-8")
        )
        raw = ContentPackRecord.from_dict(data)
        cls.record = build_pack_record(
            raw.content,
            revision=raw.revision,
            qa_problems=raw.qa_problems,
            replacement_for=raw.replacement_for,
        )

    def validate(self, content):
        config = load_config().raw
        validate_content_pack(
            content,
            source_language="English",
            target_language="German",
            language_variety="Standard German used in Germany; no dialects",
            words_per_short=config["content"]["words_per_short"],
            dialogue_turns_per_long=config["content"]["dialogue_turns_per_long"],
        )

    def test_fixture_validates(self):
        self.validate(self.record.content)

    def test_long_lesson_must_use_short_vocabulary(self):
        content = json.loads(json.dumps(self.record.content))
        content["long_videos"][0]["dialogue"][0]["german"] = "Guten Morgen!"
        content["long_videos"][0]["dialogue"][1]["german"] = "Mein Vorname ist Mia."
        with self.assertRaises(ContentValidationError):
            self.validate(content)

    def test_long_lesson_must_start_with_a_and_alternate_speakers(self):
        content = json.loads(json.dumps(self.record.content))
        content["long_videos"][0]["dialogue"][0]["speaker"] = "B"
        with self.assertRaisesRegex(
            ContentValidationError,
            "must start with A and alternate A/B exactly",
        ):
            self.validate(content)

    def test_issue_body_round_trip(self):
        restored = parse_pack_record(format_issue_body(self.record))
        self.assertEqual(restored.pack_id, self.record.pack_id)
        self.assertEqual(restored.content, self.record.content)

    def test_record_integrity(self):
        validate_record_integrity(self.record)

    def test_upload_manifest_round_trip(self):
        body = format_issue_body(self.record)
        manifest = {"pack_id": self.record.pack_id, "assets": {"short-1": {"video_id": "abc123"}}}
        restored = read_upload_manifest(write_upload_manifest(body, manifest))
        self.assertEqual(restored, manifest)


if __name__ == "__main__":
    unittest.main()
