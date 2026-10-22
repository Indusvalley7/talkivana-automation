import unittest

from language_video_automation.approvals import Decision, is_authorized, parse_approval_command


class ApprovalTests(unittest.TestCase):
    def test_content_and_video_approvals_are_distinct(self):
        self.assertEqual(parse_approval_command("APPROVE CONTENT").decision, Decision.APPROVE_CONTENT)
        self.assertEqual(parse_approval_command("APPROVE VIDEO").decision, Decision.APPROVE_VIDEO)

    def test_targeted_retry_and_revision_feedback(self):
        parsed = parse_approval_command("RETRY VOICE: German line 3 is too fast")
        self.assertEqual(parsed.decision, Decision.RETRY_VOICE)
        self.assertEqual(parsed.reason, "German line 3 is too fast")
        revised = parse_approval_command("REVISE CONTENT: Replace the café example")
        self.assertEqual(revised.decision, Decision.REVISE_CONTENT)
        visuals = parse_approval_command("RETRY VISUALS: Move the German line lower")
        self.assertEqual(visuals.decision, Decision.RETRY_SLIDES)
        self.assertEqual(visuals.reason, "Move the German line lower")

    def test_casual_language_is_not_approval(self):
        for body in ("APPROVE", "looks good", "yes", "approved!", "👍", "> APPROVE VIDEO"):
            self.assertEqual(parse_approval_command(body).decision, Decision.IGNORE)

    def test_only_configured_actor(self):
        self.assertTrue(is_authorized("Indusvalley7", "Indusvalley7", "Indusvalley7"))
        self.assertFalse(is_authorized("attacker", "Indusvalley7", "Indusvalley7"))


if __name__ == "__main__":
    unittest.main()
