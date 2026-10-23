import unittest

from language_video_automation.config import project_root


class WorkflowSafetyTests(unittest.TestCase):
    def test_every_scheduled_operational_workflow_has_an_independent_gate(self):
        workflows = (
            "generate-draft.yml",
            "timing-agent.yml",
            "cleanup-previews.yml",
            "preflight.yml",
        )
        for filename in workflows:
            with self.subTest(workflow=filename):
                text = (project_root() / ".github" / "workflows" / filename).read_text(
                    encoding="utf-8"
                )
                self.assertIn("github.event_name == 'workflow_dispatch'", text)
                self.assertIn("vars.TALKIVANA_DAILY_AUTOMATION == 'true'", text)

    def test_production_matrix_comes_from_the_frozen_descriptor(self):
        text = (
            project_root() / ".github" / "workflows" / "process-approval.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(text.count("fromJSON(needs.production_prepare.outputs.asset_matrix)"), 3)
        self.assertIn("talkivana-full-controlled-sample", text)


if __name__ == "__main__":
    unittest.main()
