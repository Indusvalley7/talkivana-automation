import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from language_video_automation.config import project_root
from language_video_automation.models import ContentValidationError
from language_video_automation.topic_history import (
    load_excel_video_history,
    topics_are_repeated,
    validate_unique_topics,
)


class TopicHistoryTests(unittest.TestCase):
    def test_reads_video_headings_from_schedule_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Schedule Matrix"
            sheet.cell(5, 2, "YouTube video / Short")
            sheet.cell(6, 2, "Short 1: Weather Words")
            sheet.cell(7, 2, "Video 1: Buying a Train Ticket")
            workbook.save(path)
            self.assertEqual(
                load_excel_video_history(path),
                ["Short 1: Weather Words", "Video 1: Buying a Train Ticket"],
            )

    def test_semantic_topic_family_blocks_cosmetic_repetition(self):
        self.assertTrue(
            topics_are_repeated(
                "Ordering coffee and cake at a local café",
                "Video 2: Ordering Refreshments at a Café",
            )
        )
        self.assertFalse(
            topics_are_repeated(
                "Checking into a hotel",
                "Video 2: Ordering Refreshments at a Café",
            )
        )

    def test_pack_validation_rejects_an_existing_excel_topic(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        with self.assertRaises(ContentValidationError):
            validate_unique_topics(
                fixture,
                existing_topics=["Video 1: Introducing Yourself to a New Neighbor"],
            )


if __name__ == "__main__":
    unittest.main()
