# AgentClean

**Your code. Your commits. Your attribution.**

A browser-based four-step cleanup tool from Canadian AI Solutions.

## Features

- Scan a public GitHub repository without a token.
- Scan private repositories with a fine-grained GitHub personal access token.
- Detect optional attribution footers from Claude Code, Codex, Cursor, and Gemini CLI.
- Preview the before/after commit messages before changing anything.
- Rewrite eligible linear Git history after explicit confirmation, with a backup branch.

## Running locally

Install the Vercel CLI and run `vercel dev` in the project root. The frontend is `index.html`, and the API is `api/repository.js`.

No application environment variables are required. Users optionally enter a GitHub fine-grained PAT scoped to the repository with **Contents: Read and write** permission for private scanning and write operations.

## Safety and limitations

- The app edits matching *commit message lines* only; it never deletes or edits source code.
- The UI requires a confirmed preview, checked warning, and the exact phrase `REWRITE HISTORY` before rewriting.
- Rewriting creates a timestamped backup branch before updating the chosen branch.
- The app refuses protected branches, signed commits, merge histories, and histories of 100 or more commits.
- The app rechecks the branch HEAD before applying the final ref update; nonetheless, repository owners should coordinate a maintenance window and ensure no concurrent pushes.
- Commit hashes necessarily change when rewriting, and rewritten commits lose cryptographic signatures.
- Repository tokens are held in browser-tab memory and sent only to the Vercel API over HTTPS as necessary; they are not persisted by this code.
- This is intentionally not a general-purpose rewriting engine for complex repository histories. For those, use a carefully reviewed local Git migration.

## Security model

GitHub credentials are supplied per request rather than stored in a database. The API uses them only for calls to GitHub, and the frontend clears the token after a successful cleanup. Host this only behind HTTPS and don't enable request-header logging. Because GitHub does not offer transactions for multi-commit rewrites, the backup branch is the recovery point if an operation fails.

## Future improvements

GitHub App authentication, scanning other branches, batching large histories through a job queue, dry-run export, and dedicated protection for open pull requests.

MIT licensed.
