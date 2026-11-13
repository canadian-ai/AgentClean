#!/usr/bin/env python3
"""Preserve Git history and contributor identities while removing optional AI trailers.

Requires git-filter-repo: python -m pip install git-filter-repo
Preview by default; --apply rewrites a temporary clone. --push additionally
backs up the original remote HEAD and pushes with an explicit lease.
"""
import argparse
import datetime
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

TRAILERS = (
    rb"^[ \t]*co-authored-by:[ \t]*claude(?:[ \t]+code)?\b.*$",
    rb"^[ \t]*\xf0\x9f\xa4\x96[ \t]*generated with \[?claude code\]?.*$",
    rb"^[ \t]*claude-session:[ \t]*.*$",
    rb"^[ \t]*co-authored-by:[ \t]*(?:openai[ \t]+)?codex\b.*$",
    rb"^[ \t]*(?:generated|assisted) (?:with|by) (?:openai[ \t]+)?codex\b.*$",
    rb"^[ \t]*co-authored-by:[ \t]*cursor\b.*$",
    rb"^[ \t]*(?:generated|assisted) (?:with|by) cursor\b.*$",
    rb"^[ \t]*co-authored-by:[ \t]*(?:google[ \t]+)?gemini\b.*$",
    rb"^[ \t]*(?:generated|assisted) (?:with|by) gemini(?: cli)?\b.*$",
)
PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in TRAILERS)


def clean_message(message):
    """Remove only optional AI attribution lines; never touch author/committer."""
    lines = message.split(b"\n")
    filtered = [line for line in lines if not any(p.match(line) for p in PATTERNS)]
    if len(filtered) == len(lines):
        return message
    return re.sub(rb"\n{3,}", b"\n\n", b"\n".join(filtered)).rstrip(b"\n") + b"\n"


def git(*args, cwd=None, capture=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    ).stdout


def summarize(repo, branch):
    head = git("rev-parse", branch, cwd=repo).strip().decode()
    tree = git("rev-parse", branch + "^{tree}", cwd=repo).strip().decode()
    count = int(git("rev-list", "--count", branch, cwd=repo).strip())
    merges = int(git("rev-list", "--min-parents=2", "--count", branch, cwd=repo).strip())
    raw = git("log", "--format=%B%x00", branch, cwd=repo)
    matches = sum(clean_message(msg) != msg for msg in raw.split(b"\x00") if msg.strip())
    return dict(head=head, tree=tree, commits=count, merges=merges, matches=matches)


def rewrite(source, branch, push=False):
    if shutil.which("git-filter-repo") is None:
        raise RuntimeError("Install git-filter-repo first: python -m pip install git-filter-repo")
    # A single-branch clone includes all ancestors and merge parents of this branch.
    # Preserve its original object database and every author/committer identity.
    with tempfile.TemporaryDirectory(prefix="agentclean-") as directory:
        repo = pathlib.Path(directory) / "repo"
        git("clone", "--no-tags", "--single-branch", "--branch", branch,
            source, str(repo), capture=False)
        before = summarize(repo, "HEAD")
        if before["matches"] == 0:
            print("No matching trailers; no rewrite needed.")
            return
        old = before["head"]
        # Validate that the target branch has not moved since the initial clone.
        remote_ref = "refs/heads/" + branch
        advertised = git("ls-remote", "--heads", "origin", remote_ref, cwd=repo).decode().split()
        if not advertised or advertised[0] != old:
            raise RuntimeError("Remote branch changed during clone; aborting")
        # Build the callback from this trusted local script, not user input.
        callback = "import re\npatterns = (" + ",".join(repr(p.pattern) for p in PATTERNS) + ",)\n" + (
            "lines = commit.message.split(b'\\n')\n"
            "filtered = [line for line in lines if not any(re.match(p, line, re.I) for p in patterns)]\n"
            "if len(filtered) != len(lines):\n"
            "    commit.message = re.sub(rb'\\n{3,}', b'\\n\\n', b'\\n'.join(filtered)).rstrip(b'\\n') + b'\\n'\n"
        )
        subprocess.run(["git", "filter-repo", "--force", "--refs", remote_ref,
                        "--commit-callback", callback], cwd=repo, check=True)
        # filter-repo operates on a local branch; don't assume HEAD moved.
        after = summarize(repo, branch)
        for invariant in ("tree", "commits", "merges"):
            if before[invariant] != after[invariant]:
                raise RuntimeError(f"History invariant {invariant} changed; no push")
        if after["matches"] != 0:
            raise RuntimeError("Matching agent attribution remains; no push")
        print(f"Verified: {before['commits']} commits, {before['merges']} merges, unchanged tip tree.")
        print(f"Rewritten HEAD: {after['head']}; original HEAD: {old}")
        if not push:
            print("Local rewrite verified; remote unchanged. Use --apply --push to publish.")
            return
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = f"refs/heads/agentclean-backup-{stamp}"
        # A backup exists on the remote before the force-with-lease update.
        git("push", "origin", f"{old}:{backup}", cwd=repo, capture=False)
        git("push", f"--force-with-lease={remote_ref}:{old}",
            "origin", f"{after['head']}:{remote_ref}", cwd=repo, capture=False)
        print(f"Published rewritten {branch}. Remote backup: {backup}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="Git URL, e.g. https://github.com/owner/repo.git")
    parser.add_argument("--branch", default="master", help="Branch to inspect or rewrite")
    parser.add_argument("--apply", action="store_true", help="Create and verify temporary rewrite")
    parser.add_argument("--push", action="store_true", help="Publish with remote backup and lease (requires --apply)")
    parser.add_argument("--confirm", default="", help="Must equal REWRITE HISTORY when --push is set")
    args = parser.parse_args()
    if args.push and (not args.apply or args.confirm != "REWRITE HISTORY"):
        parser.error("--push requires --apply --confirm 'REWRITE HISTORY'")
    if not args.apply:
        with tempfile.TemporaryDirectory(prefix="agentclean-preview-") as directory:
            git("clone", "--no-tags", "--single-branch", "--branch", args.branch,
                args.repository, directory, capture=False)
            stats = summarize(directory, "HEAD")
            print(f"{stats['commits']} commits; {stats['merges']} merge commits; "
                  f"{stats['matches']} commits with removable attribution.")
            print("Read-only preview. To rewrite locally, use --apply.")
        return
    rewrite(args.repository, args.branch, args.push)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"AgentClean stopped: {exc}", file=sys.stderr)
        sys.exit(1)
