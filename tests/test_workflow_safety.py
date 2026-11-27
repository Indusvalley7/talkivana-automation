import unittest

from language_video_automation.config import project_root


class WorkflowSafetyTests(unittest.TestCase):
    def test_every_scheduled_operational_workflow_has_an_independent_gate(self):
        workflows = {
            "generate-draft.yml": "TALKIVANA_CONTENT_AUTOMATION",
            "timing-agent.yml": "TALKIVANA_ANALYTICS_AUTOMATION",
            "cleanup-previews.yml": "TALKIVANA_CLEANUP_AUTOMATION",
            "preflight.yml": "TALKIVANA_CONTENT_AUTOMATION",
        }
        for filename, variable in workflows.items():
            with self.subTest(workflow=filename):
                text = (project_root() / ".github" / "workflows" / filename).read_text(
                    encoding="utf-8"
                )
                self.assertIn("github.event_name == 'workflow_dispatch'", text)
                self.assertIn(f"vars.{variable} == 'true'", text)

    def test_production_matrix_comes_from_the_frozen_descriptor(self):
        text = (
            project_root() / ".github" / "workflows" / "process-approval.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(text.count("fromJSON(needs.production_prepare.outputs.asset_matrix)"), 3)
        self.assertIn("talkivana-full-controlled-sample", text)
        self.assertIn("*-thumbnail.jpg", text)
        self.assertEqual(text.count('"resume_video"'), 3)

    def test_daily_generation_dispatches_unattended_production_only_when_enabled(self):
        text = (
            project_root() / ".github" / "workflows" / "generate-draft.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("TALKIVANA_UNATTENDED_AUTOMATION == 'true'", text)
        self.assertIn("gh workflow run process-approval.yml", text)
        self.assertIn('--field "issue_number=$ISSUE_NUMBER"', text)

    def test_unattended_production_uses_the_same_qa_pipeline_then_finalizes(self):
        text = (
            project_root() / ".github" / "workflows" / "process-approval.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("production-prepare \\\n              --automatic", text)
        self.assertIn("production-finalize", text)
        self.assertIn("Automatically schedule the exact QA-verified private files", text)

    def test_failure_email_is_failure_only_and_has_no_success_trigger(self):
        text = (
            project_root() / ".github" / "workflows" / "failure-email.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("'[\"failure\",\"timed_out\"]'", text)
        self.assertNotIn("conclusion == 'success'", text)
        self.assertIn("scripts/send_failure_email.py", text)

    def test_voice_generation_retries_from_segment_checkpoints(self):
        text = (
            project_root() / ".github" / "workflows" / "process-approval.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("for attempt in 1 2", text)
        self.assertIn("retrying automatically from completed audio checkpoints", text)

    def test_thumbnail_backfill_is_manual_and_never_schedules_videos(self):
        text = (
            project_root() / ".github" / "workflows" / "refresh-thumbnails.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        self.assertIn("refresh-thumbnails", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("production-publish", text)


if __name__ == "__main__":
    unittest.main()
