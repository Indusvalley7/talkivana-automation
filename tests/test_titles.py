import copy
import json
import unittest

from language_video_automation.config import project_root
from language_video_automation.models import ContentValidationError
from language_video_automation.titles import (
    find_title_collisions,
    titles_are_confusingly_similar,
    validate_unique_titles,
)


class TitleUniquenessTests(unittest.TestCase):
    def test_generic_prefix_and_plural_do_not_hide_a_collision(self):
        self.assertTrue(
            titles_are_confusingly_similar(
                "German Directions Vocabulary",
                "German Direction Vocabulary",
            )
        )
        self.assertTrue(
            titles_are_confusingly_similar(
                "Public Transport Vocabulary",
                "German Public Transport Words",
            )
        )

    def test_specific_actions_are_allowed_on_a_shared_broad_topic(self):
        self.assertFalse(
            titles_are_confusingly_similar(
                "Buying a Train Ticket at the Station",
                "Excuse Me, Where Is the Train Station?",
            )
        )

    def test_pack_validation_rejects_a_previously_uploaded_heading(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        duplicate = fixture["long_videos"][0]["title"]
        with self.assertRaises(ContentValidationError):
            validate_unique_titles(fixture, reserved_titles=[duplicate])

    def test_four_distinct_titles_have_no_collision(self):
        self.assertEqual(
            find_title_collisions([
                "Street and Turn Words in German",
                "Morning Routine Essentials",
                "Excuse Me, Where Is the Train Station?",
                "Getting Coffee Before Work",
            ]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
