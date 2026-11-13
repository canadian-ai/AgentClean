"""Regression tests for AgentClean's commit-message cleanup rules."""
import importlib.util
import os
import shutil
import subprocess
import tempfile
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


@unittest.skipUnless(shutil.which("git-filter-repo"), "requires git-filter-repo")
class HistoryIntegrationTests(unittest.TestCase):
    """Exercise the actual filter engine on a repository with a merge commit."""

    def run_git(self, *args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()

    def test_merge_history_rewrite_keeps_tree_and_author(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "original.git"
            work = Path(tmp) / "work"
            self.run_git("init", "--bare", str(src))
            self.run_git("init", "-b", "master", str(work))
            self.run_git("config", "user.name", "Original Author", cwd=work)
            self.run_git("config", "user.email", "human@example.test", cwd=work)
            (work / "README.md").write_text("original code\n")
            self.run_git("add", ".", cwd=work)
            self.run_git("commit", "-m", "init", cwd=work)
            self.run_git("checkout", "-b", "feature", cwd=work)
            (work / "feature.txt").write_text("feature\n")
            self.run_git("add", ".", cwd=work)
            self.run_git("commit", "-m", "feature", "-m",
                         "Co-authored-by: Claude Code <bot@example.test>", cwd=work)
            self.run_git("checkout", "master", cwd=work)
            (work / "master.txt").write_text("master\n")
            self.run_git("add", ".", cwd=work)
            self.run_git("commit", "-m", "master work", cwd=work)
            self.run_git("merge", "--no-ff", "feature", "-m", "merge feature", cwd=work)
            self.run_git("remote", "add", "origin", str(src), cwd=work)
            self.run_git("push", "-u", "origin", "master", cwd=work)
            before = module.summarize(work, "master")
            module.rewrite(str(src), "master", push=True)
            self.run_git("fetch", "origin", "master", cwd=work)
            after = module.summarize(work, "origin/master")
            self.assertEqual(before["tree"], after["tree"])
            self.assertEqual(before["commits"], after["commits"])
            self.assertEqual(before["merges"], after["merges"])
            self.assertEqual(after["matches"], 0)
            self.assertNotEqual(before["head"], after["head"])
            authors = self.run_git("log", "--format=%an <%ae>", "origin/master", cwd=work)
            self.assertTrue(all(a == "Original Author <human@example.test>" for a in authors.splitlines()))
            backups = self.run_git("for-each-ref", "--format=%(refname)", "refs/heads/agentclean-backup-*", cwd=src)
            self.assertTrue(backups)


if __name__ == "__main__":
    unittest.main()
