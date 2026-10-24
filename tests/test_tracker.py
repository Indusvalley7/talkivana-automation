import csv
import io
import unittest

from language_video_automation.github_api import Issue
from language_video_automation.tracker import (
    TRACKER_FIELDS,
    _render_csv,
    _render_markdown,
    _review_state,
)


class TrackerTests(unittest.TestCase):
    def test_scheduled_pack_is_approved_but_not_automatically_published(self):
        issue = Issue(
            number=1,
            title="Pack",
            body="",
            state="closed",
            labels=("talkivana", "pack-scheduled"),
            html_url="https://example.test/issues/1",
        )
        approved, rejected, reason = _review_state(
            issue,
            [{"user": {"login": "Indusvalley7"}, "body": "APPROVE VIDEO"}],
            approver_login="Indusvalley7",
        )
        self.assertEqual((approved, rejected), ("Yes", "No"))
        self.assertIn("scheduled", reason)

    def test_csv_quotes_multiline_content_descriptions(self):
        row = {field: "" for field in TRACKER_FIELDS}
        row.update({
            "s_no": "1",
            "youtube_video_or_short_name": "Video 1: Test",
            "content_description": "First line\nSecond line",
        })
        rendered = _render_csv([row])
        parsed = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(parsed[0]["content_description"], "First line\nSecond line")

    def test_markdown_discloses_when_it_is_a_recent_records_view(self):
        rows = []
        for index in range(2):
            row = {field: "" for field in TRACKER_FIELDS}
            row.update({
                "s_no": str(index + 1),
                "youtube_video_or_short_name": f"Video {index + 1}: Test",
                "approved": "Yes",
                "rejected": "No",
                "successfully_published": "No",
            })
            rows.append(row)
        rendered = _render_markdown(rows, total_rows=250)
        self.assertIn("Showing the newest 2 of 250 records", rendered)
        self.assertIn("complete analysis-ready history", rendered)


if __name__ == "__main__":
    unittest.main()
