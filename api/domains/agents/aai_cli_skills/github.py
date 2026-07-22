"""aai-cli github skill docs."""

GITHUB_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/github_skill.md",
        "skill_content": r"""\
# aai-cli GitHub Skill

Agent reference for the `aai-cli github` command group.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, site URLs,
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flags

Three flags are required on **every** command:

- `--profile github-work` — always include it
- `--owner OWNER` — the GitHub org or user; always pass explicitly, never rely on the profile default
- `--repo REPO` — bare repository slug (e.g. `my-repo`); always pass explicitly

The only exception is `repos list`, which does not take `--repo`.

```
aai-cli github <command> --owner OWNER --repo REPO --profile github-work [other flags]
```
## Profile and repo selection

GitHub profiles use bearer-token auth:

```toml
[profiles.github-work]
provider = "github"
auth_type = "bearer_token"
token_secret = "github.token"
owner = "my-org"
repo = "my-repo"
```

Most commands accept `--owner OWNER --repo REPO` overrides. When omitted they fall back to `profile.owner` / `profile.repo`. `repos list` falls back to `profile.org` (org repos) or the authenticated user's repos when `org` is unset.

**Multiple repositories:** if the configured credential lists more than one repository, additional profiles `github-work-2`, `github-work-3`, ... are set up — one per repo, all sharing the same token and owner. Check the `## Configured Integrations` section of this agent's tool context (TOOLS.md) for the authoritative profile-to-repo mapping; don't guess which numbered profile maps to which repo. Since `--repo` always overrides the profile default, the simplest approach is usually to keep `--profile github-work` and just pass whichever `--repo` you need explicitly — you rarely need to switch `--profile`.

**No repository configured:** if the credential has zero repositories configured, `profile.repo` is absent entirely. `--repo REPO` then becomes mandatory on every command that needs one — omitting it returns a `config_error`.

## Response shapes

Successful command output is JSON on stdout.

**Get commands** return the raw GitHub API response.

**Download commands** (`prs diff --output`, `source get --output`, `actions runs|jobs logs download`) write bytes to disk and return:

```json
{ "output": "local/logs/file.txt", "bytes": 1234 }
```

**Text commands** (`prs diff` without `--output`, `source get` without `--output`/`--meta`) return a JSON string.

**Normalized paginated commands** aggregate GitHub pages up to `--limit` and return:

```json
{ "values": [], "size": 0, "truncated": false }
```

This normalized shape applies to: `prs files`, `prs commits`, `prs timeline`, `prs reviews list`, `prs review-comments list`, `branches list`, and `source history`. Older list commands such as `repos list`, `prs list`, `issues list`, and `prs comments list` return raw provider pages.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "message": "..." },
  "message": "provider returned HTTP 422",
  "operation": "pr-reviews.create",
  "service": "github",
  "status": 422
}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `config_error` | Missing or malformed config, profile, or owner/repo setting |
| `auth_error` | Missing credentials, invalid token, or provider 401/403 |
| `not_found` | Provider returned 404 |
| `rate_limited` | Provider returned 429 |
| `provider_api_error` | Provider returned another 4xx/5xx |
| `internal_error` | Local request, response, or IO failure |

Exit code is non-zero on any error.

## PR review workflow

For review agents, prefer this flow:

1. `prs get` to verify PR metadata and pick up `head.sha`.
2. `prs files` to identify changed files with patches.
3. `prs diff --output local/logs/pr-N.diff` for large reviews.
4. `source get <sha> <path>` to inspect exact file contents at the reviewed commit when needed.
5. Either:
   - `prs comments create` for a single general/issue-level comment, OR
   - `prs review-comments create --path FILE --line N --commit-id SHA` for a single inline comment, OR
   - `prs reviews create --event REQUEST_CHANGES --body "..." --comments-json '[...]'` for a grouped multi-comment review.

GitHub's REST API has three distinct comment resources:

| Command group | Endpoint | Use for |
|---|---|---|
| `prs comments` | `/issues/{n}/comments` | General PR discussion comments (no file/line) |
| `prs review-comments` | `/pulls/{n}/comments` | Inline review comments tied to a file and line |
| `prs reviews` | `/pulls/{n}/reviews` | Grouped reviews (approve / request changes / comment) optionally bundling multiple inline comments in one call |

Inline review comments require `--commit-id SHA`, `--path FILE`, and `--line N` (with optional `--side LEFT|RIGHT`, `--start-line N`, `--start-side LEFT|RIGHT` for multi-line ranges). Replies use `--in-reply-to COMMENT_ID --body TEXT` and route to the `replies` endpoint.

# GitHub Actions Skill

Commands under `aai-cli github actions`.

These commands return raw GitHub provider responses except for log downloads, which write bytes to disk and return `{ output, bytes }`.

---

## actions runs list

List workflow runs for a repository.

```
aai-cli github actions runs list [--owner OWNER] [--repo REPO] --profile github-work
                                  [--branch BRANCH] [--status STATUS] [--event EVENT] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--branch` | no | Filter by branch name |
| `--status` | no | Provider status filter, e.g. `completed`, `in_progress`, `failure` |
| `--event` | no | Workflow trigger event, e.g. `push`, `pull_request` |
| `--limit` | no | Provider page length. Default: `50` |

**Example**

```
aai-cli github actions runs list --status failure --limit 10 --profile github-work
```

---

## actions runs get

Fetch a single workflow run by ID.

```
aai-cli github actions runs get <RUN_ID> [--owner OWNER] [--repo REPO] --profile github-work
```

---

## actions runs logs download

Download a workflow run log archive (ZIP) to a local file.

```
aai-cli github actions runs logs download <RUN_ID> --output PATH [--owner OWNER] [--repo REPO] --profile github-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `RUN_ID` | yes | GitHub workflow run ID |
| `--output` | yes | Local file path for downloaded archive bytes |

**Example**

```
aai-cli github actions runs logs download 123456789 --output local/logs/github-run-123456789.zip --profile github-work
```

---

## actions jobs list

List jobs for a workflow run.

```
aai-cli github actions jobs list <RUN_ID> [--owner OWNER] [--repo REPO] [--limit N] [--all-attempts] --profile github-work
```

`--all-attempts` switches GitHub's filter from `latest` (default) to `all`.

---

## actions jobs get

Fetch a single job by ID.

```
aai-cli github actions jobs get <JOB_ID> [--owner OWNER] [--repo REPO] --profile github-work
```

---

## actions jobs logs download

Download a job log to a local file (typically plain text).

```
aai-cli github actions jobs logs download <JOB_ID> --output PATH [--owner OWNER] [--repo REPO] --profile github-work
```

```json
{ "output": "local/logs/github-job.txt", "bytes": 12345 }
```

# GitHub Branches Skill

Commands under `aai-cli github branches`.

---

## branches list

List branches for a repository. Returns the normalized paginated shape.

```
aai-cli github branches list [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
                              [--name-contains TEXT | --name-prefix TEXT]
                              [--protected true|false]
```

| Flag | Required | Description |
|---|---|---|
| `--owner` | **yes** | GitHub org or user |
| `--repo` | **yes** | Bare repository slug (e.g. `my-repo`) |
| `--limit` | no | Max branches to return after filtering. Default: `50` |
| `--name-contains` | no | Case-insensitive substring match (client-side) |
| `--name-prefix` | no | Anchored prefix match (client-side) |
| `--protected` | no | Server-side filter for protected branches |

`--name-contains` and `--name-prefix` are mutually exclusive. GitHub does not expose a server-side name filter on this endpoint, so both flags filter inside the paginator.

**Examples**

```
aai-cli github branches list --owner my-org --repo my-repo --limit 20 --profile github-work
aai-cli github branches list --name-contains feature --profile github-work
aai-cli github branches list --name-prefix release- --profile github-work
aai-cli github branches list --protected true --profile github-work
```

```json
{
  "size": 1,
  "truncated": false,
  "values": [
    {
      "name": "release-2026-05",
      "commit": { "sha": "abc123" },
      "protected": false
    }
  ]
}
```

---

## branches get

Fetch a single branch by name. Returns the full raw API response.

```
aai-cli github branches get <BRANCH_NAME> [--owner OWNER] [--repo REPO] --profile github-work
```

| Argument | Required | Description |
|---|---|---|
| `BRANCH_NAME` | yes | Branch name, for example `main` or `feature/auth` |

**Example**

```
aai-cli github branches get main --owner my-org --repo my-repo --profile github-work
```

# GitHub Issues Skill

Commands under `aai-cli github issues`.

All issue commands accept `--owner OWNER --repo REPO`; both fall back to `profile.owner` / `profile.repo`.

---

## issues list

List issues for a repository. Returns the raw GitHub provider page.

```
aai-cli github issues list [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Provider page length. Default: `50` |

---

## issues get

Fetch a single issue.

```
aai-cli github issues get <NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
```

---

## issues create

Create an issue. Use `--json` to pass a raw GitHub create body; flags override matching JSON fields.

```
aai-cli github issues create [--owner OWNER] [--repo REPO] --profile github-work
                             [--json JSON_OR_PATH] --title TEXT [--body TEXT]
```

| Flag | Required | Description |
|---|---|---|
| `--title` | yes unless JSON covers it | Issue title |
| `--body` | no | Issue body (Markdown) |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin) |

---

## issues update

Update an issue. Title, body, and state are individually overridable.

```
aai-cli github issues update <NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
                              [--json JSON_OR_PATH] [--title TEXT] [--body TEXT] [--state STATE]
```

`--state` accepts GitHub values such as `open` or `closed`.

---

## issues delete

GitHub does not actually delete issues via REST. This command sends a state-close PATCH and returns the resulting issue.

```
aai-cli github issues delete <NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
```

Verify with `issues get` before relying on this command.

# GitHub Pull Requests Skill

Commands under `aai-cli github prs`.

All commands accept `--owner OWNER --repo REPO`; both fall back to `profile.owner` / `profile.repo`.

GitHub exposes three distinct PR comment resources. This skill keeps them as separate command groups so each maps cleanly to its REST endpoint:

| Command group | Endpoint | Use for |
|---|---|---|
| `prs comments` | `/repos/{o}/{r}/issues/{n}/comments` | General/issue-level PR comments (no file/line) |
| `prs review-comments` | `/repos/{o}/{r}/pulls/{n}/comments` | Inline review comments tied to a file and line |
| `prs reviews` | `/repos/{o}/{r}/pulls/{n}/reviews` | Grouped reviews (approve / request changes / comment), optionally bundling many inline comments |

---

## prs list

List pull requests for a repository. Returns the raw GitHub provider page.
By default GitHub returns only **open** PRs — pass `--state` to change that.

```
aai-cli github prs list [--owner OWNER] [--repo REPO] [--limit N] [--state STATE] [--sort updated] --profile github-work
```

`--state` accepts `open` (default), `closed`, or `all`. GitHub has no "merged"
state: to find **merged** PRs, use `--state closed` and keep those whose
`merged_at` is not null.

`--sort updated` orders by most-recently-updated first. Without it the page is in
creation order, so a PR opened long ago but merged recently sits deep in the list
and can fall past `--limit`. Use `--sort updated` when you need recently-merged
PRs regardless of when they were opened.

---

## prs get

Fetch a single pull request. Returns the full raw API response.

```
aai-cli github prs get <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
```

---

## prs create

Create a pull request. Use `--json` to pass a raw GitHub create body; flags override matching JSON fields.

```
aai-cli github prs create [--owner OWNER] [--repo REPO] --profile github-work
                          [--json JSON_OR_PATH] --title TEXT
                          --head BRANCH --base BRANCH [--body TEXT]
```

| Flag | Required | Description |
|---|---|---|
| `--title` | yes unless JSON covers it | Pull request title |
| `--head` | yes unless JSON covers it | Source branch name (alias `--source`) |
| `--base` | yes unless JSON covers it | Destination branch name (alias `--destination`) |
| `--body` | no | Pull request description (Markdown) |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin) |

**Example**

```
aai-cli github prs create --title "Fix auth timeout" --head fix-auth-timeout --base main --body "Ready for review." --profile github-work
```

---

## prs close / decline / delete

GitHub does not delete pull requests via REST. In this CLI slice, `close`, `decline`, and `delete` share the same provider call (PATCH state to `closed`).

```
aai-cli github prs close <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
aai-cli github prs decline <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
aai-cli github prs delete <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
```

Verify with `prs get` before using these commands.

---

## prs diff

Fetch a unified diff for a pull request. Without `--output`, stdout is a JSON string containing diff text. With `--output`, bytes are written to disk and stdout is metadata.

Internally requests the PR endpoint with `Accept: application/vnd.github.v3.diff`.

```
aai-cli github prs diff <PR_NUMBER> [--owner OWNER] [--repo REPO] [--output PATH] --profile github-work
```

**Examples**

```
aai-cli github prs diff 42 --profile github-work
aai-cli github prs diff 42 --output local/logs/pr-42.diff --profile github-work
```

```json
{ "output": "local/logs/pr-42.diff", "bytes": 675 }
```

---

## prs files

List changed files with patches for a pull request. Returns the normalized paginated shape.

```
aai-cli github prs files <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max changed-file entries to return. Default: `50` |

```json
{
  "size": 1,
  "truncated": false,
  "values": [
    {
      "filename": "README.md",
      "status": "modified",
      "additions": 3,
      "deletions": 1,
      "patch": "@@ -1,3 +1,5 @@\n..."
    }
  ]
}
```

---

## prs commits

List commits on a pull request. Returns the normalized paginated shape.

```
aai-cli github prs commits <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
```

---

## prs timeline

List pull request timeline events. Returns the normalized paginated shape. Internally calls `GET /repos/{o}/{r}/issues/{n}/timeline`.

```
aai-cli github prs timeline <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
```

Timeline events include reviews, commits, label changes, assignments, cross-references, and more.

---

## prs comments list / get / create / update / delete

General/issue-level PR comments. These do not have a file or line and live under `/repos/{o}/{r}/issues/{n}/comments`. Returns raw GitHub provider pages.

```
aai-cli github prs comments list <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
aai-cli github prs comments get <PR_NUMBER> <COMMENT_ID> [--owner OWNER] [--repo REPO] --profile github-work
aai-cli github prs comments create <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
                                    [--json JSON_OR_PATH] --body TEXT
aai-cli github prs comments update <PR_NUMBER> --comment <COMMENT_ID> --profile github-work
                                    [--owner OWNER] [--repo REPO]
                                    [--json JSON_OR_PATH] --body TEXT
aai-cli github prs comments delete <PR_NUMBER> <COMMENT_ID> [--owner OWNER] [--repo REPO] --profile github-work
```

`--body` becomes the comment body (Markdown). `--json` accepts a full GitHub create/update body and is overridden by `--body`.

**Examples**

```
aai-cli github prs comments create 42 --body "Reviewed by agent" --profile github-work
aai-cli github prs comments update 42 --comment 1234567 --body "Updated comment" --profile github-work
```

---

## prs review-comments list / get / create / update / delete

Inline review comments tied to a file and line. Endpoint: `/repos/{o}/{r}/pulls/{n}/comments`. Returns the normalized paginated shape on `list`.

```
aai-cli github prs review-comments list <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
aai-cli github prs review-comments get <PR_NUMBER> <COMMENT_ID> [--owner OWNER] [--repo REPO] --profile github-work
aai-cli github prs review-comments create <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
                                            [--json JSON_OR_PATH] --body TEXT
                                            --path FILE --commit-id SHA
                                            [--line N] [--side LEFT|RIGHT]
                                            [--start-line N] [--start-side LEFT|RIGHT]
                                            [--in-reply-to COMMENT_ID]
aai-cli github prs review-comments update <PR_NUMBER> --comment <COMMENT_ID> --profile github-work
                                            [--owner OWNER] [--repo REPO]
                                            [--json JSON_OR_PATH] --body TEXT
aai-cli github prs review-comments delete <PR_NUMBER> <COMMENT_ID> [--owner OWNER] [--repo REPO] --profile github-work
```

For a brand-new inline comment, `--body`, `--path`, and `--commit-id` are required. `--line` is the new-file line number; `--side` is `LEFT` (old file) or `RIGHT` (new file, default). For multi-line comments use `--start-line` and `--start-side`.

For a reply to an existing inline comment, pass `--in-reply-to COMMENT_ID --body TEXT`. The reply routes to `/pulls/{n}/comments/{COMMENT_ID}/replies` and only requires a body.

**Examples**

```
aai-cli github prs review-comments create 42 \
  --body "Please rename this variable" \
  --path src/lib.rs --line 120 --commit-id abc123def --profile github-work

aai-cli github prs review-comments create 42 \
  --body "Agreed" --in-reply-to 999988887 --profile github-work

aai-cli github prs review-comments update 42 --comment 999988887 --body "Edited" --profile github-work
aai-cli github prs review-comments delete 42 999988887 --profile github-work
```

---

## prs reviews list / get / create

Grouped pull request reviews. Endpoint: `/repos/{o}/{r}/pulls/{n}/reviews`. `list` returns the normalized paginated shape; `get` returns raw; `create` returns raw.

```
aai-cli github prs reviews list <PR_NUMBER> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
aai-cli github prs reviews get <PR_NUMBER> <REVIEW_ID> [--owner OWNER] [--repo REPO] --profile github-work
aai-cli github prs reviews create <PR_NUMBER> [--owner OWNER] [--repo REPO] --profile github-work
                                   [--json JSON_OR_PATH]
                                   [--event APPROVE|REQUEST_CHANGES|COMMENT|PENDING]
                                   [--body TEXT] [--commit-id SHA]
                                   [--comments-json JSON_ARRAY_OR_PATH]
```

| Flag | Required | Description |
|---|---|---|
| `--event` | no | One of `APPROVE`, `REQUEST_CHANGES`, `COMMENT`, `PENDING`. Omitting it submits a `PENDING` review (a draft) per GitHub semantics |
| `--body` | no | Review summary text. Required by GitHub when `--event` is `REQUEST_CHANGES` or `COMMENT` |
| `--commit-id` | no | Commit SHA the review applies to. Defaults to the PR's latest commit when omitted |
| `--comments-json` | no | JSON array of inline review comments to attach in the same review (see below) |
| `--json` | no | Full GitHub review create body. Flags override matching fields |

Each entry in `--comments-json` follows GitHub's review-comments shape, e.g.:

```json
[
  { "path": "src/lib.rs", "line": 120, "body": "rename this" },
  { "path": "src/main.rs", "line": 5, "side": "LEFT", "body": "remove" }
]
```

**Examples**

```
aai-cli github prs reviews create 42 --event APPROVE --body "LGTM" --profile github-work

aai-cli github prs reviews create 42 \
  --event REQUEST_CHANGES \
  --body "A few nits inline" \
  --commit-id abc123def \
  --comments-json '[{"path":"src/lib.rs","line":120,"body":"rename"}]' --profile github-work

aai-cli github prs reviews list 42 --limit 5 --profile github-work
```

Use `prs review-comments create` when you only have one inline note; use `prs reviews create` when you want to bundle a summary plus several inline comments in a single API call.

# GitHub Repositories Skill

Commands under `aai-cli github repos`.

---

## repos list

List repositories accessible to the configured profile. Uses `profile.org` if set (org repos), otherwise falls back to the authenticated user's repos. Returns the raw GitHub provider page.

```
aai-cli github repos list [--limit N] --profile github-work
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Provider page length. Default: `50` |

**Example**

```
aai-cli github repos list --limit 5 --profile github-work
```

---

## repos get

Fetch a single repository. Returns the full raw API response.

```
aai-cli github repos get [--owner OWNER] [--repo REPO] --profile github-work
```

| Flag | Required | Description |
|---|---|---|
| `--owner` | **yes** | GitHub org or user |
| `--repo` | **yes** | Bare repository slug (e.g. `my-repo`) |

**Example**

```
aai-cli github repos get --owner my-org --repo my-repo --profile github-work
```

# GitHub Source Skill

Commands under `aai-cli github source`.

`COMMIT` can be a branch name, tag, or commit SHA accepted by GitHub. File paths are encoded path segment by path segment; a leading slash is ignored.

---

## source get

Fetch source file content or source metadata.

```
aai-cli github source get <COMMIT> <PATH> [--owner OWNER] [--repo REPO] --profile github-work
                            [--output PATH] [--meta]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `COMMIT` | yes | Branch, tag, or commit SHA |
| `PATH` | yes | Repository-relative file path |
| `--owner` | **yes** | GitHub org or user |
| `--repo` | **yes** | Bare repository slug (e.g. `my-repo`) |
| `--output` | no | Write raw bytes to a local file and return `{ output, bytes }` |
| `--meta` | no | Return GitHub JSON metadata for the path (uses default JSON Accept) |

`--output` and `--meta` conflict. Without either flag, text files are returned as a JSON string fetched with `Accept: application/vnd.github.v3.raw`. Use `--output` for binary-safe downloads.

**Examples**

```
aai-cli github source get main README.md --owner my-org --repo my-repo --profile github-work
aai-cli github source get abc123def src/main.rs --output local/logs/main-src-main.rs --profile github-work
aai-cli github source get main README.md --meta --profile github-work
```

```json
{ "output": "local/logs/main-src-main.rs", "bytes": 4096 }
```

---

## source history

List commits that modified a file. Returns the normalized paginated shape. Internally calls `GET /repos/{owner}/{repo}/commits?path=PATH&sha=REF`.

```
aai-cli github source history <COMMIT> <PATH> [--owner OWNER] [--repo REPO] [--limit N] --profile github-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `COMMIT` | yes | Branch, tag, or commit SHA used as the `sha` filter |
| `PATH` | yes | Repository-relative file path |
| `--limit` | no | Max history entries to return. Default: `50` |

**Example**

```
aai-cli github source history main README.md --limit 20 --profile github-work
```

GitHub's REST API does not expose a per-line blame endpoint. `source history` is the closest REST analog for agents; per-line annotation is only available via GitHub's GraphQL API.
""",
    },
]
