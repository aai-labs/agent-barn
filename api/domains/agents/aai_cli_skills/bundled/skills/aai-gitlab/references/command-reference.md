# aai-cli GitLab Skill

Agent reference for the `aai-cli gitlab` command group.

## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile and project selection

```toml
[profiles.gitlab-work]
provider = "gitlab"
auth_type = "bearer_token"
token_secret = "gitlab.token"
# Omit for gitlab.com. A self-hosted instance sets its API root, including /api/v4.
base_url = "https://gitlab.example.com/api/v4"
# Optional default project.
repo = "group/subgroup/app"
```

`--project` takes a numeric ID or a full path, and overrides `profile.repo`. The CLI encodes it for you.

## Response shapes

**Get commands** return the raw GitLab response.

**List commands** walk pages up to `--limit` (default 50) and return:

```json
{ "values": [], "size": 0, "truncated": false }
```

`truncated: true` means the limit was reached; raise `--limit` to see more.

**`source get`** returns `{ "content": "..." }` and **`jobs log`** returns `{ "log": "..." }`. With `--output PATH` they write to disk and return `{ "output": "PATH", "bytes": 1234 }`. Binary files need `--output`.

## Projects

```bash
aai-cli gitlab projects list [--search TEXT] [--all] [--limit N]
aai-cli gitlab projects get [PROJECT]
```

`projects list` shows projects the token is a member of. `--all` includes every project it can see, which on gitlab.com is all public projects.

## Merge requests

```bash
aai-cli gitlab mrs list [--project P] [--state opened|closed|locked|merged|all] [--source-branch B] [--target-branch B] [--search TEXT] [--limit N]
aai-cli gitlab mrs get IID [--project P]
aai-cli gitlab mrs create --source-branch B --target-branch B --title T [--description D] [--json BODY] [--project P]
aai-cli gitlab mrs update IID [--title T] [--description D] [--target-branch B] [--json BODY] [--project P]
aai-cli gitlab mrs close IID [--project P]
aai-cli gitlab mrs reopen IID [--project P]
aai-cli gitlab mrs diffs IID [--limit N] [--output PATH] [--project P]
aai-cli gitlab mrs commits IID [--limit N] [--project P]
aai-cli gitlab mrs approve IID [--project P]
aai-cli gitlab mrs unapprove IID [--project P]
aai-cli gitlab mrs approvals IID [--project P]
```

There is no `mrs merge` command. If merging is genuinely part of the task, use `gitlab request put projects/<encoded-project>/merge_requests/<iid>/merge --allow-write`.

### Notes and discussions

Notes are flat comments. Discussions are threads, and the only way to comment on a diff line.

```bash
aai-cli gitlab mrs notes list IID [--limit N] [--project P]
aai-cli gitlab mrs notes get IID NOTE_ID [--project P]
aai-cli gitlab mrs notes create IID --body TEXT [--project P]
aai-cli gitlab mrs notes update IID NOTE_ID --body TEXT [--project P]
aai-cli gitlab mrs notes delete IID NOTE_ID [--project P]
aai-cli gitlab mrs discussions list IID [--limit N] [--project P]
aai-cli gitlab mrs discussions create IID --body TEXT [--json BODY] [--project P]
```

To comment on a line, take `diff_refs` from `mrs get` and pass a `position`:

```bash
aai-cli gitlab mrs discussions create 7 --project group/app --json '{
  "body": "This can panic on an empty list.",
  "position": {
    "position_type": "text",
    "base_sha": "<diff_refs.base_sha>",
    "start_sha": "<diff_refs.start_sha>",
    "head_sha": "<diff_refs.head_sha>",
    "old_path": "src/main.rs",
    "new_path": "src/main.rs",
    "new_line": 42
  }
}'
```

Use `new_line` for an added line, `old_line` for a removed line, and both for an unchanged line.

## Issues

```bash
aai-cli gitlab issues list [--project P] [--state opened|closed|all] [--search TEXT] [--labels A,B] [--limit N]
aai-cli gitlab issues get IID [--project P]
aai-cli gitlab issues create --title T [--description D] [--json BODY] [--project P]
aai-cli gitlab issues update IID [--title T] [--description D] [--state-event close|reopen] [--json BODY] [--project P]
aai-cli gitlab issues notes list IID [--limit N] [--project P]
aai-cli gitlab issues notes create IID --body TEXT [--project P]
```

## Branches and commits

```bash
aai-cli gitlab branches list [--search TEXT] [--limit N] [--project P]
aai-cli gitlab branches get BRANCH [--project P]
aai-cli gitlab branches create BRANCH --ref REF [--project P]
aai-cli gitlab branches delete BRANCH [--project P]
aai-cli gitlab commits list [--ref-name REF] [--path FILE] [--limit N] [--project P]
aai-cli gitlab commits get SHA [--project P]
aai-cli gitlab commits diff SHA [--limit N] [--project P]
```

## Source

```bash
aai-cli gitlab source get REF PATH [--output FILE] [--project P]
aai-cli gitlab source tree [--ref REF] [--path DIR] [--recursive] [--limit N] [--project P]
```

## Pipelines and jobs

```bash
aai-cli gitlab pipelines list [--ref REF] [--status STATUS] [--limit N] [--project P]
aai-cli gitlab pipelines get ID [--project P]
aai-cli gitlab pipelines jobs ID [--limit N] [--project P]
aai-cli gitlab pipelines retry ID [--project P]
aai-cli gitlab pipelines cancel ID [--project P]
aai-cli gitlab jobs get ID [--project P]
aai-cli gitlab jobs log ID [--output FILE] [--project P]
```

To find out why a pipeline failed, run `pipelines jobs`, pick the failed job, then `jobs log`.

## Generic requests

For anything else, call the REST API relative to the profile's API root. Encode project paths yourself:

```bash
aai-cli gitlab request get projects/group%2Fapp/labels --query per_page=50
aai-cli gitlab request post projects/group%2Fapp/labels --allow-write --json '{"name":"bug","color":"#ff0000"}'
```

Absolute URLs are rejected. Mutating methods require `--allow-write`.
