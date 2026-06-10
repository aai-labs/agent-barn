"""aai-cli bitbucket skill docs."""

BITBUCKET_SKILLS: list[dict[str, str]] = [
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_skill.md",
        "skill_content": """\
# aai-cli Bitbucket Skill

Agent reference for the `aai-cli bitbucket` command group.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, site URLs,
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flag

Every command requires `--profile bitbucket-work`. Always include it.

```
aai-cli bitbucket <command> --profile bitbucket-work [other flags]
```
## Profile and repo selection

Bitbucket Cloud profiles normally use Atlassian basic auth:

```toml
[profiles.bitbucket-work]
auth_type = "basic_api_token"
workspace = "my-workspace"
repo = "my-repo"
email = "agent@example.com"
api_token_secret = "bitbucket.api_token"
```

Commands that operate on a repository accept `--repo`. A plain repo slug uses `profile.workspace`; `workspace/repo` overrides both. Newer commands also accept `--owner WORKSPACE --repo REPO`.

## Response shapes

Successful command output is JSON on stdout.

**Get commands** return the raw Bitbucket API response.

**Download commands** (`prs diff --output`, `source get --output`, pipeline log downloads) write bytes to disk and return:

```json
{ "output": "local/logs/file.txt", "bytes": 1234 }
```

**Text commands** (`prs diff` without `--output`, `source get` for text files) return a JSON string.

**Normalized paginated commands** aggregate Bitbucket `next` pages up to `--limit` and return:

```json
{ "values": [], "size": 0, "truncated": false }
```

This normalized shape applies to `prs diffstat`, `prs commits`, `prs activity`, `prs comments list`, `branches list`, `commits list`, and `source history`. Older list commands such as `repos list`, `prs list`, and `pipelines list` return raw provider pages.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "error": { "message": "..." } },
  "message": "provider returned HTTP 400",
  "operation": "prs.comments.create",
  "service": "bitbucket",
  "status": 400
}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `config_error` | Missing or malformed config, profile, or repo/workspace setting |
| `auth_error` | Missing credentials, invalid token, or provider 401/403 |
| `not_found` | Provider returned 404 |
| `rate_limited` | Provider returned 429 |
| `provider_api_error` | Provider returned another 4xx/5xx |
| `internal_error` | Local request, response, or IO failure |

Exit code is non-zero on any error.

## PR review workflow

For review agents, prefer this flow:

1. `prs get` to verify PR metadata.
2. `prs diffstat` to identify changed files.
3. `prs diff --output local/logs/pr-N.diff` for large reviews.
4. `source get <commit> <path>` to inspect exact file contents when needed.
5. `prs comments create` for summary comments or inline comments.

Use `--inline-to` for lines added in the new file, `--inline-from` for lines removed from the old file, and always pass `--inline-path` for inline comments.

## Resource reference

Read the file for the resource you need:

| Resource | Commands | File |
|---|---|---|
| Repositories | list, get | [bitbucket_repo_skill/bitbucket_repo_skill.md](bitbucket_repo_skill/bitbucket_repo_skill.md) |
| Pull requests | list, get, create, close/decline/delete, diff, diffstat, commits, activity, comments | [bitbucket_pr_skill/bitbucket_pr_skill.md](bitbucket_pr_skill/bitbucket_pr_skill.md) |
| Branches | list, get | [bitbucket_branch_skill/bitbucket_branch_skill.md](bitbucket_branch_skill/bitbucket_branch_skill.md) |
| Commits | list, get | [bitbucket_commit_skill/bitbucket_commit_skill.md](bitbucket_commit_skill/bitbucket_commit_skill.md) |
| Source | get, history | [bitbucket_source_skill/bitbucket_source_skill.md](bitbucket_source_skill/bitbucket_source_skill.md) |
| Pipelines | list, get, steps list/get, step logs download | [bitbucket_pipeline_skill/bitbucket_pipeline_skill.md](bitbucket_pipeline_skill/bitbucket_pipeline_skill.md) |

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_branch_skill/bitbucket_branch_skill.md",
        "skill_content": """\
# Bitbucket Branches Skill

Commands under `aai-cli bitbucket branches`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

---

## branches list

List branches for a repository. Returns the normalized paginated shape.

```
aai-cli bitbucket branches list [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
                                [--limit N] [--name-contains TEXT | --name-prefix TEXT]
```

| Flag | Required | Description |
|---|---|---|
| `--repo` | no | Repo slug, or `workspace/repo`. Defaults to profile repo |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--limit` | no | Max branches to return after filtering. Default: `50` |
| `--name-contains` | no | Case-insensitive substring match using Bitbucket BBQL |
| `--name-prefix` | no | Prefix match. Uses BBQL as a server hint, then filters with client-side `starts_with` |

`--name-contains` and `--name-prefix` are mutually exclusive. A hidden `--query` escape hatch exists for raw Bitbucket BBQL, but prefer the agent-safe flags above.

**Examples**

```
aai-cli bitbucket branches list --repo my-workspace/my-repo --limit 20
aai-cli bitbucket branches list --name-contains feature
aai-cli bitbucket branches list --name-prefix release-
```

```json
{
  "size": 1,
  "truncated": false,
  "values": [
    {
      "name": "release-2026-05",
      "target": { "hash": "abc123" },
      "type": "branch"
    }
  ]
}
```

---

## branches get

Fetch a single branch by name. Returns the full raw API response.

```
aai-cli bitbucket branches get <BRANCH_NAME> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument | Required | Description |
|---|---|---|
| `BRANCH_NAME` | yes | Branch name, for example `main` or `feature/auth` |

**Example**

```
aai-cli bitbucket branches get main --repo my-workspace/my-repo
```

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_commit_skill/bitbucket_commit_skill.md",
        "skill_content": """\
# Bitbucket Commits Skill

Commands under `aai-cli bitbucket commits`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

---

## commits list

List commits for a repository. Returns the normalized paginated shape.

```
aai-cli bitbucket commits list [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
                               [--limit N] [--branch BRANCH] [--include REV] [--exclude REV]
```

| Flag | Required | Description |
|---|---|---|
| `--repo` | no | Repo slug, or `workspace/repo`. Defaults to profile repo |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--limit` | no | Max commits to return. Default: `50` |
| `--branch` | no | Branch name. Implemented as Bitbucket `include` and takes precedence over `--include` |
| `--include` | no | Include commits reachable from this rev |
| `--exclude` | no | Exclude commits reachable from this rev |

**Examples**

```
aai-cli bitbucket commits list --repo my-workspace/my-repo --branch main --limit 10
aai-cli bitbucket commits list --include feature/auth --exclude main --limit 25
```

```json
{
  "size": 1,
  "truncated": false,
  "values": [
    {
      "hash": "abc123def456",
      "message": "Update README",
      "type": "commit"
    }
  ]
}
```

---

## commits get

Fetch a single commit by SHA. Returns the full raw API response.

```
aai-cli bitbucket commits get <SHA> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument | Required | Description |
|---|---|---|
| `SHA` | yes | Full or abbreviated commit hash accepted by Bitbucket |

**Example**

```
aai-cli bitbucket commits get abc123def456 --repo my-workspace/my-repo
```

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_pipeline_skill/bitbucket_pipeline_skill.md",
        "skill_content": """\
# Bitbucket Pipelines Skill

Commands under `aai-cli bitbucket pipelines`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

These commands return raw Bitbucket provider responses except for log downloads, which write bytes to disk and return `{ output, bytes }`.

---

## pipelines list

List pipeline runs for a repository.

```
aai-cli bitbucket pipelines list [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
                                  [--branch BRANCH] [--status STATUS] [--sort FIELD] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--repo` | no | Repo slug, or `workspace/repo`. Defaults to profile repo |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--branch` | no | Filter by target branch |
| `--status` | no | Provider status filter, for example `COMPLETED` |
| `--sort` | no | Provider sort field |
| `--limit` | no | Provider page length. Default: `50` |

**Example**

```
aai-cli bitbucket pipelines list --repo my-workspace/my-repo --branch main --status COMPLETED --limit 10
```

---

## pipelines get

Fetch a single pipeline by UUID. Returns the full raw API response.

```
aai-cli bitbucket pipelines get <PIPELINE_UUID> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument | Required | Description |
|---|---|---|
| `PIPELINE_UUID` | yes | Bitbucket pipeline UUID |

---

## pipelines steps list

List steps for a pipeline. Returns the raw API response.

```
aai-cli bitbucket pipelines steps list <PIPELINE_UUID> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

---

## pipelines steps get

Fetch a single pipeline step. Returns the full raw API response.

```
aai-cli bitbucket pipelines steps get <PIPELINE_UUID> <STEP_UUID> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument | Required | Description |
|---|---|---|
| `PIPELINE_UUID` | yes | Bitbucket pipeline UUID |
| `STEP_UUID` | yes | Bitbucket step UUID |

---

## pipelines steps logs download

Download a pipeline step log to a local file.

```
aai-cli bitbucket pipelines steps logs download <PIPELINE_UUID> <STEP_UUID>
                                                 [--log LOG_UUID] --output PATH
                                                 [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PIPELINE_UUID` | yes | Bitbucket pipeline UUID |
| `STEP_UUID` | yes | Bitbucket step UUID |
| `--output` | yes | Local file path for downloaded log bytes |
| `--log` | no | Optional log UUID when Bitbucket exposes multiple logs for a step |

**Example**

```
aai-cli bitbucket pipelines steps logs download "{pipeline-uuid}" "{step-uuid}" --output local/logs/bitbucket-step.log
```

```json
{ "output": "local/logs/bitbucket-step.log", "bytes": 12345 }
```

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_pr_skill/bitbucket_pr_skill.md",
        "skill_content": """\
# Bitbucket Pull Requests Skill

Commands under `aai-cli bitbucket prs`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

Most commands accept `--repo REPO_OR_WORKSPACE_REPO`. Newer commands also accept `--owner WORKSPACE --repo REPO`.

---

## prs list

List pull requests for a repository. Returns the raw Bitbucket provider page.

```
aai-cli bitbucket prs list [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--repo` | no | Repo slug, or `workspace/repo`. Defaults to profile repo |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--limit` | no | Provider page length. Default: `50` |

**Example**

```
aai-cli bitbucket prs list --repo my-workspace/my-repo --limit 5
```

---

## prs get

Fetch a single pull request. Returns the full raw API response.

```
aai-cli bitbucket prs get <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PR_NUMBER` | yes | Numeric pull request ID |
| `--repo` | no | Repo slug, or `workspace/repo` |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |

**Example**

```
aai-cli bitbucket prs get 42 --repo my-workspace/my-repo
```

---

## prs create

Create a pull request. `--title`, `--source`, and `--destination` are the normal minimal flags. Use `--json` to pass a raw Bitbucket create body; individual flags override matching JSON fields.

```
aai-cli bitbucket prs create [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
                             [--json JSON_OR_PATH] --title TEXT
                             --source BRANCH --destination BRANCH [--body TEXT]
```

| Flag | Required | Description |
|---|---|---|
| `--repo` | no | Repo slug, or `workspace/repo` |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--title` | yes unless JSON covers it | Pull request title |
| `--source` | yes unless JSON covers it | Source branch name |
| `--destination` | yes unless JSON covers it | Destination branch name |
| `--body` | no | Pull request description |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin) |

**Example**

```
aai-cli bitbucket prs create --repo my-workspace/my-repo --title "Fix auth timeout" --source fix-auth-timeout --destination main --body "Ready for review."
```

---

## prs close / decline / delete

Close a pull request through Bitbucket's decline endpoint. In this CLI slice, `close`, `decline`, and `delete` share the same provider call.

```
aai-cli bitbucket prs close <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
aai-cli bitbucket prs decline <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
aai-cli bitbucket prs delete <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

Verify with `prs get` before using these commands.

---

## prs diff

Fetch a unified diff for a pull request. Without `--output`, stdout is a JSON string containing diff text. With `--output`, bytes are written to disk and stdout is metadata.

```
aai-cli bitbucket prs diff <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE] [--output PATH]
```

| Flag | Required | Description |
|---|---|---|
| `--output` | no | Write the diff to a file instead of printing it as a JSON string |

**Examples**

```
aai-cli bitbucket prs diff 42 --repo my-workspace/my-repo
aai-cli bitbucket prs diff 42 --repo my-workspace/my-repo --output local/logs/pr-42.diff
```

```json
{ "output": "local/logs/pr-42.diff", "bytes": 675 }
```

---

## prs diffstat

List changed files for a pull request. Returns the normalized paginated shape.

```
aai-cli bitbucket prs diffstat <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max changed-file entries to return. Default: `50` |

**Example**

```
aai-cli bitbucket prs diffstat 42 --limit 100
```

```json
{
  "size": 1,
  "truncated": false,
  "values": [
    {
      "new": { "path": "README.md" },
      "old": { "path": "README.md" },
      "status": "modified"
    }
  ]
}
```

---

## prs commits

List commits on a pull request. Returns the normalized paginated shape.

```
aai-cli bitbucket prs commits <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max commits to return. Default: `50` |

---

## prs activity

List pull request activity events. Returns the normalized paginated shape.

```
aai-cli bitbucket prs activity <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max activity events to return. Default: `50` |

---

## prs comments list

List pull request comments. Returns the normalized paginated shape. `--inline-only` filters across all fetched pages.

```
aai-cli bitbucket prs comments list <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO]
                                      [--owner WORKSPACE] [--limit N] [--inline-only]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PR_NUMBER` | yes | Numeric pull request ID |
| `--limit` | no | Max comments to return after filtering. Default: `50` |
| `--inline-only` | no | Return only comments that include an `inline` object |

---

## prs comments get

Fetch a single pull request comment. Returns the full raw API response.

```
aai-cli bitbucket prs comments get <PR_NUMBER> <COMMENT_ID> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

| Argument | Required | Description |
|---|---|---|
| `PR_NUMBER` | yes | Numeric pull request ID |
| `COMMENT_ID` | yes | Numeric comment ID |

---

## prs comments create

Create a general, inline, or reply comment. Use `--body` for plain text or `--json` for a raw Bitbucket comment body; flags override matching JSON fields.

```
aai-cli bitbucket prs comments create <PR_NUMBER> [--repo REPO_OR_WORKSPACE_REPO]
                                         [--owner WORKSPACE] [--json JSON_OR_PATH]
                                         --body TEXT [--inline-path FILE]
                                         [--inline-from LINE_BEFORE] [--inline-to LINE_AFTER]
                                         [--parent-id COMMENT_ID]
```

| Flag | Required | Description |
|---|---|---|
| `--body` | yes unless JSON covers `content` | Comment text. Stored as `content.raw` |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin) |
| `--inline-path` | no | File path for inline comment. Required when `--inline-from` or `--inline-to` is set |
| `--inline-from` | no | Old-file line number for removed lines |
| `--inline-to` | no | New-file line number for added lines |
| `--parent-id` | no | Parent comment ID for a reply |

**Examples**

```
aai-cli bitbucket prs comments create 42 --body "Review complete."
aai-cli bitbucket prs comments create 42 --body "Please rename this variable" --inline-path src/lib.rs --inline-to 120
aai-cli bitbucket prs comments create 42 --body "Agreed" --parent-id 799066024
```

---

## prs comments update

Update an existing pull request comment. The comment ID is passed with `--comment`.

```
aai-cli bitbucket prs comments update <PR_NUMBER> --comment COMMENT_ID
                                         [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
                                         [--json JSON_OR_PATH] --body TEXT
                                         [--inline-path FILE] [--inline-from LINE_BEFORE]
                                         [--inline-to LINE_AFTER] [--parent-id COMMENT_ID]
```

The inline and reply flags behave the same as `comments create`.

---

## prs comments delete

Delete a pull request comment.

```
aai-cli bitbucket prs comments delete <PR_NUMBER> <COMMENT_ID> [--repo REPO_OR_WORKSPACE_REPO] [--owner WORKSPACE]
```

Verify with `comments get` before deleting.

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_repo_skill/bitbucket_repo_skill.md",
        "skill_content": """\
# Bitbucket Repositories Skill

Commands under `aai-cli bitbucket repos`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

---

## repos list

List repositories in the configured workspace. Returns the raw Bitbucket provider page.

```
aai-cli bitbucket repos list [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Provider page length. Default: `50` |

**Example**

```
aai-cli bitbucket repos list --limit 3
```

```json
{
  "pagelen": 3,
  "size": 147,
  "values": [
    {
      "full_name": "my-workspace/my-repo",
      "name": "my-repo",
      "slug": "my-repo",
      "type": "repository"
    }
  ]
}
```

---

## repos get

Fetch a single repository by slug or `workspace/repo`.

```
aai-cli bitbucket repos get <REPO_SLUG_OR_WORKSPACE_REPO>
```

| Argument | Required | Description |
|---|---|---|
| `REPO_SLUG_OR_WORKSPACE_REPO` | yes | Repo slug using profile workspace, or `workspace/repo` |

**Example**

```
aai-cli bitbucket repos get my-workspace/my-repo
```

```json
{
  "full_name": "my-workspace/my-repo",
  "name": "my-repo",
  "slug": "my-repo",
  "type": "repository",
  "uuid": "{repo-uuid}"
}
```

""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/bitbucket_skill/bitbucket_source_skill/bitbucket_source_skill.md",
        "skill_content": """\
# Bitbucket Source Skill

Commands under `aai-cli bitbucket source`. For global flags, repo selection, and error shapes see [../bitbucket_skill.md](../bitbucket_skill.md).

`COMMIT` can be a branch name, tag, or commit hash accepted by Bitbucket. File paths are encoded path segment by path segment; a leading slash is ignored.

---

## source get

Fetch source file content or source metadata.

```
aai-cli bitbucket source get <COMMIT> <PATH> [--repo REPO_OR_WORKSPACE_REPO]
                              [--owner WORKSPACE] [--output PATH] [--meta]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `COMMIT` | yes | Branch, tag, or commit hash |
| `PATH` | yes | Repository-relative file path |
| `--repo` | no | Repo slug, or `workspace/repo`. Defaults to profile repo |
| `--owner` | no | Workspace. Use with `--repo` as a plain slug |
| `--output` | no | Write raw bytes to a local file and return `{ output, bytes }` |
| `--meta` | no | Return Bitbucket JSON metadata using `format=meta` |

`--output` and `--meta` conflict. Without either flag, text files are returned as a JSON string.

**Examples**

```
aai-cli bitbucket source get main README.md --repo my-workspace/my-repo
aai-cli bitbucket source get abc123def src/main.rs --output local/logs/main-src-main.rs
aai-cli bitbucket source get main README.md --meta
```

```json
{ "output": "local/logs/main-src-main.rs", "bytes": 4096 }
```

---

## source history

List commits that modified a file. Returns the normalized paginated shape.

```
aai-cli bitbucket source history <COMMIT> <PATH> [--repo REPO_OR_WORKSPACE_REPO]
                                  [--owner WORKSPACE] [--limit N]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `COMMIT` | yes | Branch, tag, or commit hash |
| `PATH` | yes | Repository-relative file path |
| `--limit` | no | Max history entries to return. Default: `50` |

**Example**

```
aai-cli bitbucket source history main README.md --limit 20
```

Bitbucket Cloud does not expose a dedicated per-line blame REST endpoint. `source history` is the closest REST analog for agents.

""",
    },
]
