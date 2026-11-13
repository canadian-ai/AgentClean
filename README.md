# AgentClean

**Your code. Your commits. Your attribution.**

A browser-based four-step cleanup tool from Canadian AI Solutions.

## Features

- Scan a public GitHub repository without a token.
- Scan private repositories with a fine-grained GitHub personal access token.
- Detect optional attribution footers from Claude Code, Codex, Cursor, and Gemini CLI.
- Preview the before/after commit messages before changing anything.
- Rewrite eligible linear Git history in the browser after explicit confirmation, with a backup branch.
- For large histories, merges, or signed commits, use the local history-preserving cleanup CLI below. It preserves original author/committer identities, commit trees, and merge structure.

## Running locally

Install the Vercel CLI and run `vercel dev` in the project root. The frontend is `index.html`, and the API is `api/repository.js`.

No application environment variables are required. Users optionally enter a GitHub fine-grained PAT scoped to the repository with **Contents: Read and write** permission for private scanning and write operations.

## Large-history cleanup (Git CLI)

The browser rewrite is deliberately limited to small, unsigned, linear histories.
For repositories like `canadian-ai/girl`, use the local CLI with
[`git-filter-repo`](https://github.com/newren/git-filter-repo).
It changes **only optional AI attribution lines in commit messages**. All commits,
original authors/committers, file trees, and merges remain represented, but changed
commit IDs and cryptographic signatures cannot be retained.

```sh
python -m pip install git-filter-repo
python scripts/history-clean.py https://github.com/canadian-ai/girl.git --branch master
python scripts/history-clean.py https://github.com/canadian-ai/girl.git --branch master --apply
# Only during a coordinated maintenance window, when ready to publish:
python scripts/history-clean.py https://github.com/canadian-ai/girl.git --branch master --apply --push --confirm 'REWRITE HISTORY'
```

The push step first creates `agentclean-backup-<timestamp>` on the remote,
verifies that the tip tree, number of commits and merge commits are unchanged,
then uses `--force-with-lease` to refuse concurrent updates.
Coordinate with maintainers; pause CI/PR merges and update clones, open PRs,
release references and any signed-commit policies after rewriting.
The original signed history remains accessible through the backup branch.
The GitHub Contributors graph derives from author identity and is not erased;
this operation removes optional coding-agent co-author attribution trailers only.

Run CLI unit tests: `python -m unittest discover -s tests -p 'test_history_clean.py'`.

## Safety and limitations

- The app edits matching *commit message lines* only; it never deletes or edits source code.
- The UI requires a confirmed preview, checked warning, and the exact phrase `REWRITE HISTORY` before rewriting.
- Rewriting creates a timestamped backup branch before updating the chosen branch.
- The browser app refuses protected branches, signed commits, merge histories, and histories of 100 or more commits; the local CLI handles large/merge histories with explicit backups and leases.
- The app rechecks the branch HEAD before applying the final ref update; nonetheless, repository owners should coordinate a maintenance window and ensure no concurrent pushes.
- Commit hashes necessarily change when rewriting, and rewritten commits lose cryptographic signatures.
- Repository tokens are held in browser-tab memory and sent only to the Vercel API over HTTPS as necessary; they are not persisted by this code.
- This is intentionally not a general-purpose rewriting engine for complex repository histories. For those, use a carefully reviewed local Git migration.

## Security model

GitHub credentials are supplied per request rather than stored in a database. The API uses them only for calls to GitHub, and the frontend clears the token after a successful cleanup. Host this only behind HTTPS and don't enable request-header logging. Because GitHub does not offer transactions for multi-commit rewrites, the backup branch is the recovery point if an operation fails.

## Future improvements

GitHub App authentication, scanning other branches, batching large histories through a job queue, dry-run export, and dedicated protection for open pull requests.

MIT licensed.
