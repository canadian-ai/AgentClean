"""Regression tests for AgentClean's commit-message cleanup rules."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "agentclean_history", Path(__file__).resolve().parents[1] / "scripts" / "history-clean.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CleanMessageTests(unittest.TestCase):
    def test_preserves_message_without_agent_trailers(self):
        original = b"feat: add validation\n\nKeep ordinary body lines.\n"
        self.assertEqual(module.clean_message(original), original)

    def test_removes_only_agent_attribution(self):
        original = (
            b"feat: keep history\n\n"
            b"Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>\n"
            b"Claude-Session: https://claude.ai/code/session_abc\n"
            b"Co-authored-by: Human <human@example.test>\n"
        )
        cleaned = module.clean_message(original)
        self.assertNotIn(b"Claude", cleaned)
        self.assertIn(b"Co-authored-by: Human", cleaned)
        self.assertIn(b"feat: keep history", cleaned)

    def test_other_agents(self):
        for trailer in (
            b"Co-authored-by: OpenAI Codex <bot@example.test>",
            b"Co-authored-by: Cursor <bot@example.test>",
            b"Co-authored-by: Google Gemini <bot@example.test>",
        ):
            with self.subTest(trailer=trailer):
                self.assertEqual(module.clean_message(b"fix: something\n\n" + trailer + b"\n"), b"fix: something\n")

    def test_does_not_delete_actual_author(self):
        msg = b"feat: teamwork\n\nCo-authored-by: Engineer <engineer@example.test>\n"
        self.assertEqual(module.clean_message(msg), msg)


if __name__ == "__main__":
    unittest.main()
