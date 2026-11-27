import importlib.util
import unittest

from language_video_automation.config import project_root


def _load_mailer():
    path = project_root() / "scripts" / "send_failure_email.py"
    spec = importlib.util.spec_from_file_location("talkivana_failure_mailer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load failure mailer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FailureEmailTests(unittest.TestCase):
    def test_prefers_the_last_high_priority_error_annotation(self):
        mailer = _load_mailer()
        reason = mailer.extract_failure_reason(
            "Error: generic wrapper\n"
            "::error::First specific failure\n"
            "Process completed with exit code 1\n"
            "::error::Voice generation failed after two attempts.\n"
        )
        self.assertEqual(reason, "Voice generation failed after two attempts.")

    def test_falls_back_when_actions_has_no_specific_annotation(self):
        mailer = _load_mailer()
        reason = mailer.extract_failure_reason("A regular log line without an error annotation")
        self.assertIn("without a specific error annotation", reason)


if __name__ == "__main__":
    unittest.main()
