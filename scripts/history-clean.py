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
    rb"^[ \t]*co-authored-by:[ \t]*(?:codesmith|opencode(?:-agent)?(?:\[bot\])?)(?=[ \t]|$).*$",
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



# Classify only recognized automation identities; never infer that a human
# author is an agent just because they used AI-assisted development.
AI_IDENTITY = re.compile(r"(?:claude|codex|codesmith|cursor|gemini|opencode(?:-agent)?)", re.I)
BOT_IDENTITY = re.compile(r"(?:\[bot\]|github-actions|dependabot|renovate)", re.I)


def contributor_category(name, email):
    identity = name + " " + email
    if AI_IDENTITY.search(identity):
        return "ai-agent"
    if BOT_IDENTITY.search(identity):
        return "automation"
    return "human"


def contributor_audit(repo, branch):
    """Report actual Git author/committer identities, separate from trailers.

    It applies Git .mailmap aliases to consolidate equivalent human identities.
    Bot authors are auto-classified, not credited to a human. This is a
    Git-history approximation, not an exact GitHub Contributors API count.
    """
    raw = git("log", "--use-mailmap", "--format=%aN%x00%aE%x00%cN%x00%cE%x00%x1e", branch, cwd=repo)
    authors = {}
    committers = {}
    for record in raw.split(b"\x1e"):
        fields = record.strip(b"\n").split(b"\x00")
        if len(fields) < 4:
            continue
        author = tuple(v.decode("utf-8", "replace") for v in fields[:2])
        committer = tuple(v.decode("utf-8", "replace") for v in fields[2:4])
        authors[author] = authors.get(author, 0) + 1
        committers[committer] = committers.get(committer, 0) + 1

    def rows(identities):
        return sorted(
            (
                {"name": name, "email": email, "commits": count,
                 "category": contributor_category(name, email)}
                for (name, email), count in identities.items()
            ),
            key=lambda row: (-row["commits"], row["name"], row["email"]),
        )

    return {"authors": rows(authors), "committers": rows(committers)}


def print_contributor_check(audit):
    print("Contributor identity check (Git history, not GitHub UI):")
    for role in ("authors", "committers"):
        bots = [x for x in audit[role] if x["category"] != "human"]
        print(f"  {role}: {len(audit[role])} identities; {len(bots)} automation/AI identities")
        for item in bots:
            print(f"    [{item['category']}] {item['name']} <{item['email']}>: {item['commits']} commits")
    humans = [x for x in audit["authors"] if x["category"] == "human"]
    print(f"  Human identities (mailmap-normalized): {len(humans)}")
    print("  Automated author identities are classified without manual approval.")
    if any(x["category"] != "human" for x in audit["authors"]):
        print("  CONTRIBUTOR CHECK: INCOMPLETE (GitHub may still display bot authors)")
    else:
        print("  CONTRIBUTOR CHECK: PASS (no recognized automated Git authors)")


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
        original_audit = contributor_audit(repo, "HEAD")
        print_contributor_check(original_audit)
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
        # Rewrite the checked-out local branch, not the remote-tracking ref.
        # Disabling pruning is essential: an attribution-only edit must not
        # change the number of commits or the merge topology.
        subprocess.run(
            ["git", "filter-repo", "--force", "--refs", "refs/heads/" + branch,
             "--prune-empty", "never", "--prune-degenerate", "never",
             "--replace-refs", "delete-no-add",
             "--preserve-commit-encoding", "--commit-callback", callback],
            cwd=repo, check=True,
        )
        # filter-repo operates on a local branch; don't assume HEAD moved.
        after = summarize(repo, branch)
        updated_audit = contributor_audit(repo, branch)
        if original_audit != updated_audit:
            raise RuntimeError("Author or committer identity changed; no push")
        print_contributor_check(updated_audit)
        if after["head"] == old:
            raise RuntimeError("Filter did not update the selected branch; no push")
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
        # The source clone is local and may have a stale origin after the filter.
        # Push explicitly to the source URL; never reuse a removed remote.
        git("push", source, f"{old}:{backup}", cwd=repo, capture=False)
        git("push", f"--force-with-lease={remote_ref}:{old}",
            source, f"{after['head']}:{remote_ref}", cwd=repo, capture=False)
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
            print_contributor_check(contributor_audit(directory, "HEAD"))
            print("Read-only preview. To rewrite locally, use --apply.")
        return
    rewrite(args.repository, args.branch, args.push)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"AgentClean stopped: {exc}", file=sys.stderr)
        sys.exit(1)
