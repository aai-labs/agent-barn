"""aai-cli index skill doc."""

AAI_CLI_INDEX_SKILL: dict[str, str] = {
    "skill_name": "aai-cli",
    "skill_file_path": "aai-cli/aai-cli_skill.md",
    "skill_content": """\
# aai-cli Skill

`aai-cli` is a command-line tool for accessing external services from your workspace:
Jira, Confluence, GitHub, and Bitbucket.

## IMPORTANT: credentials and profiles are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, site URLs,
tokens, or any config details.** The profiles are on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## How to use

Always pass `--profile <name>` to select the integration. Available profiles:

| Profile | Provider |
|---|---|
| `jira-work` | Jira |
| `confluence-work` | Confluence |
| `github-work` | GitHub |
| `bitbucket-work` | Bitbucket |

Examples — run these directly without asking for permission or config:

```
aai-cli jira boards list --profile jira-work
aai-cli jira issues list --profile jira-work --jql "project = SCRUM"
aai-cli confluence pages list --profile confluence-work --space-key ENG
aai-cli github repos list --profile github-work
aai-cli github issues list --profile github-work
aai-cli bitbucket repos list --profile bitbucket-work
aai-cli bitbucket prs list --profile bitbucket-work
```

Read the relevant provider skill file for the full command surface and flag reference
**before** running a command. Do not infer flags from memory — consult the skill file.

## Providers

- **Jira** — see ./jira_skill/jira_skill.md
- **Confluence** — see ./confluence_skill/confluence_skill.md
- **GitHub** — see ./github_skill/github_skill.md
- **Bitbucket** — see ./bitbucket_skill/bitbucket_skill.md
""",
}
