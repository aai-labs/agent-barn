import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "domains/agents/scripts/openclaw/plugins/agentbarn-bot-env"
DRIVER = Path(__file__).resolve().parents[1] / "fixtures/openclaw_bot_env_driver.mjs"
BOT_A = "0000000a-0000-4000-8000-00000000000a"
BOT_B = "0000000b-0000-4000-8000-00000000000b"
STATE = "/home/node/.openclaw"
PARENT_ENV = {
    "AGENT_ID": "parent-id",
    "ARTIFACT_API_KEY": "artifact-parent",
    "MEMORY_API_KEY": "memory-parent",
    "AF_GATEWAY_TOKEN_JIRA": "jira-parent",
    "OPENCLAW_GATEWAY_TOKEN": "gateway-parent",
    "FIRECRAWL_API_KEY": "firecrawl-parent",
    "LITELLM_BASE_URL": "http://localhost:8090",
}
PARENT_NAMES = sorted(PARENT_ENV)
PLATFORMS = {"main": ["telegram", "msteams"], BOT_A: ["telegram"], BOT_B: ["discord"]}
BOT_SECRETS = {
    BOT_A: {
        "AGENT_ID": BOT_A,
        "ARTIFACT_API_KEY": "artifact-a",
        "LITELLM_API_KEY": "sk-a",
        "FIRECRAWL_API_KEY": "fc-a",
    },
    BOT_B: {"AGENT_ID": BOT_B, "ARTIFACT_API_KEY": "artifact-b", "MEMORY_API_KEY": "memory-b", "GOG_HOME": "/b"},
}


def _exec(agent_id, env=None, **event):
    params = {"command": "echo hi", **({"env": env} if env is not None else {})}
    return {"event": {"toolName": "exec", "params": params, **event}, "ctx": {"agentId": agent_id}}


def _run(tmp_path: Path, calls: list[dict], secrets=BOT_SECRETS) -> dict:
    node = shutil.which("node")
    assert node is not None, "node is required to exercise the OpenClaw plugin"
    root = tmp_path / "bots"
    for bot_id, values in secrets.items():
        (root / bot_id).mkdir(parents=True)
        for name, value in values.items():
            (root / bot_id / name).write_text(value)
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps({"config": {"parentNames": PARENT_NAMES, "platforms": PLATFORMS}, "calls": calls}))
    completed = subprocess.run(
        [node, str(DRIVER), str(PLUGIN / "index.js"), str(steps)],
        env={**os.environ, **PARENT_ENV, "BOT_SECRET_ROOT": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _env(outcome: dict) -> dict:
    return outcome["result"]["params"]["env"]


def test_the_plugin_rewrites_exec_last_and_only_exec(tmp_path):
    registrations = _run(tmp_path, [])["registrations"]

    assert registrations == [
        {"name": "before_tool_call", "options": {"priority": -1000, "matcher": ["exec"]}},
        {"name": "before_tool_call", "options": {"priority": -1000, "matcher": ["message", "automations", "cron"]}},
        {"name": "message_sending", "options": {"priority": -1000}},
    ]


def test_a_bots_command_gets_its_own_values_and_none_of_the_parents(tmp_path):
    env = _env(_run(tmp_path, [_exec(BOT_A)])["results"][0])

    assert env["AGENT_ID"] == BOT_A
    assert env["ARTIFACT_API_KEY"] == "artifact-a"
    assert env["LITELLM_API_KEY"] == "sk-a"
    for name in ("MEMORY_API_KEY", "AF_GATEWAY_TOKEN_JIRA", "OPENCLAW_GATEWAY_TOKEN"):
        assert env[name] == ""
    assert env["AAI_CONFIG"] == f"{STATE}/bots/{BOT_A}/.config/aai-cli/config.toml"
    assert env["ARTIFACT_UPLOAD_ROOTS"] == f"{STATE}/workspace-{BOT_A}"


def test_a_bot_shares_the_parents_firecrawl_and_proxy_settings(tmp_path):
    env = _env(_run(tmp_path, [_exec(BOT_A)])["results"][0])

    assert "FIRECRAWL_API_KEY" not in env
    assert "LITELLM_BASE_URL" not in env


def test_each_bot_sees_only_its_own_secret(tmp_path):
    results = _run(tmp_path, [_exec(BOT_A), _exec(BOT_B)])["results"]
    a, b = _env(results[0]), _env(results[1])

    assert b["MEMORY_API_KEY"] == "memory-b"
    assert b["GOG_HOME"] == "/b"
    assert not set(BOT_SECRETS[BOT_B].values()) - {"/b"} & set(a.values())
    assert "GOG_HOME" not in a


def test_the_models_own_env_is_kept_but_cannot_override_identity(tmp_path):
    env = _env(_run(tmp_path, [_exec(BOT_A, env={"AGENT_ID": "hacked", "EXTRA": "kept"})])["results"][0])

    assert (env["AGENT_ID"], env["EXTRA"]) == (BOT_A, "kept")


def test_the_parent_keeps_its_own_values(tmp_path):
    env = _env(_run(tmp_path, [_exec("main", env={"AGENT_ID": "hacked", "EXTRA": "kept"})])["results"][0])

    assert env == {**PARENT_ENV, "EXTRA": "kept"}


def test_the_rest_of_the_exec_call_is_untouched(tmp_path):
    outcome = _run(tmp_path, [_exec(BOT_A, background=True)])["results"][0]

    assert outcome["result"]["params"]["command"] == "echo hi"


@pytest.mark.parametrize(
    ("agent_id", "secrets"),
    [
        (None, BOT_SECRETS),
        ("0000000c-0000-4000-8000-00000000000c", BOT_SECRETS),
        (BOT_A, {BOT_A: {**BOT_SECRETS[BOT_A], "AGENT_ID": BOT_B}}),
    ],
)
def test_a_command_with_no_known_agent_or_a_bad_secret_is_refused(tmp_path, agent_id, secrets):
    outcome = _run(tmp_path, [_exec(agent_id)], secrets=secrets)["results"][0]

    assert "error" in outcome


def test_the_agent_comes_from_the_session_key_when_the_hook_names_none(tmp_path):
    calls = [
        {"event": {"toolName": "exec", "params": {"command": "echo hi"}}, "ctx": {"sessionKey": key}}
        for key in (f"agent:{BOT_A}:main", "agent:main:telegram:direct:1")
    ]
    bot, parent = _run(tmp_path, calls)["results"]

    assert _env(bot)["AGENT_ID"] == BOT_A
    assert _env(parent) == PARENT_ENV


def test_code_mode_is_refused_for_a_bot_and_left_alone_for_the_parent(tmp_path):
    results = _run(tmp_path, [_exec(BOT_A, toolKind="code_mode_exec"), _exec("main", toolKind="code_mode_exec")])[
        "results"
    ]

    assert "error" in results[0]
    assert results[1] == {"result": None}


def test_other_tools_are_left_alone(tmp_path):
    call = {"event": {"toolName": "read", "params": {"path": "x"}}, "ctx": {"agentId": BOT_A}}

    assert _run(tmp_path, [call])["results"] == [{"result": None}]


def _tool(agent_id, tool, params, account=None):
    requester = {"requester": {"channel": "telegram", "accountId": account}} if account else {}
    return {"event": {"toolName": tool, "params": params}, "ctx": {"agentId": agent_id, **requester}}


def _params(outcome):
    return outcome["result"]["params"]


def _blocked(outcome):
    return outcome["result"]["block"] is True and "account" in outcome["result"]["blockReason"]


def test_a_message_on_a_platform_the_agent_is_on_is_sent_from_its_own_account(tmp_path):
    results = _run(
        tmp_path,
        [
            _tool(BOT_A, "message", {"action": "send", "channel": "Telegram", "target": "1", "message": "hi"}),
            _tool("main", "message", {"action": "send", "channel": "telegram", "target": "1", "message": "hi"}),
        ],
    )["results"]

    assert _params(results[0]) == {
        "action": "send",
        "channel": "Telegram",
        "target": "1",
        "message": "hi",
        "accountId": BOT_A,
    }
    assert _params(results[1])["accountId"] == "default"


def test_a_bots_message_without_a_channel_is_still_sent_from_its_own_account(tmp_path):
    params = {"action": "send", "target": "channel:C123", "message": "hi"}
    outcome = _run(tmp_path, [_tool(BOT_A, "message", params)])["results"][0]

    assert _params(outcome) == {**params, "accountId": BOT_A}


def test_the_parents_message_without_a_channel_is_left_alone(tmp_path):
    params = {"action": "send", "target": "channel:C123", "message": "hi"}
    outcome = _run(tmp_path, [_tool("main", "message", params)])["results"][0]

    assert outcome == {"result": None}


@pytest.mark.parametrize(
    "params",
    [
        {"action": "send", "channel": "discord", "target": "1", "message": "hi"},
        {"action": "send", "channel": "telegram", "accountId": "default", "message": "hi"},
        {"action": "send", "accountId": BOT_B, "message": "hi"},
    ],
)
def test_a_bot_cannot_post_from_another_agents_account(tmp_path, params):
    outcome = _run(tmp_path, [_tool(BOT_A, "message", params)])["results"][0]

    assert _blocked(outcome)


def test_the_parent_cannot_post_on_a_platform_only_a_bot_uses(tmp_path):
    outcome = _run(tmp_path, [_tool("main", "message", {"action": "send", "channel": "discord", "message": "hi"})])[
        "results"
    ][0]

    assert _blocked(outcome)


@pytest.mark.parametrize("tool", ["automations", "cron"])
def test_a_scheduled_job_delivers_from_the_agents_own_account(tmp_path, tool):
    job = {
        "name": "daily",
        "delivery": {"mode": "announce", "channel": "telegram", "to": "1"},
        "failureAlert": {"channel": "telegram", "to": "1"},
    }
    outcome = _run(tmp_path, [_tool(BOT_A, tool, {"action": "add", "job": job})])["results"][0]

    pinned = _params(outcome)["job"]
    assert pinned["delivery"]["accountId"] == BOT_A
    assert pinned["failureAlert"]["accountId"] == BOT_A
    assert pinned["name"] == "daily"


@pytest.mark.parametrize(
    "job",
    [
        {"delivery": {"mode": "announce", "channel": "discord", "to": "1"}},
        {"delivery": {"mode": "announce", "channel": "telegram", "accountId": "default"}},
        {"delivery": {"mode": "announce", "failureDestination": {"channel": "discord", "to": "1"}}},
        {"failureAlert": {"channel": "discord", "to": "1"}},
    ],
)
def test_a_scheduled_job_cannot_deliver_from_another_agents_account(tmp_path, job):
    outcome = _run(tmp_path, [_tool(BOT_A, "automations", {"action": "update", "jobId": "j", "job": job})])["results"][
        0
    ]

    assert _blocked(outcome)


def test_scheduler_reads_are_left_alone(tmp_path):
    outcome = _run(tmp_path, [_tool(BOT_A, "automations", {"action": "list"})])["results"][0]

    assert outcome == {"result": None}


def test_a_bots_job_without_a_channel_delivers_from_its_own_account_when_asked_on_it(tmp_path):
    job = {"delivery": {"mode": "announce", "channel": "last"}}
    outcome = _run(tmp_path, [_tool(BOT_A, "automations", {"action": "add", "job": job}, account=BOT_A)])["results"][0]

    assert _params(outcome)["job"]["delivery"] == {"mode": "announce", "channel": "last", "accountId": BOT_A}


@pytest.mark.parametrize("account", [None, "default"])
@pytest.mark.parametrize("delivery", [{"mode": "announce"}, {"mode": "announce", "channel": "last"}])
def test_a_bots_job_without_a_channel_asked_without_its_own_account_is_left_to_its_owner(tmp_path, account, delivery):
    job = {"delivery": delivery}
    outcome = _run(tmp_path, [_tool(BOT_A, "automations", {"action": "add", "job": job}, account=account)])["results"][
        0
    ]

    assert outcome == {"result": None}


def test_the_parents_job_without_a_channel_is_left_alone(tmp_path):
    job = {"delivery": {"mode": "announce"}}
    outcome = _run(tmp_path, [_tool("main", "automations", {"action": "add", "job": job})])["results"][0]

    assert outcome == {"result": None}


def _sending(session, channel="telegram", account=None):
    ctx = {
        "channelId": channel,
        "conversationId": "1",
        "sessionKey": session,
        **({"accountId": account} if account else {}),
    }
    return {"hook": "message_sending", "event": {"to": "1", "content": "hi"}, "ctx": ctx}


@pytest.mark.parametrize("account", [None, "default", BOT_B])
def test_a_bots_post_from_another_account_is_cancelled_when_sent(tmp_path, account):
    outcome = _run(tmp_path, [_sending(f"agent:{BOT_A}:cron:j:run:1", account=account)])["results"][0]

    assert outcome["result"]["cancel"] is True
    assert "own account" in outcome["result"]["cancelReason"]


@pytest.mark.parametrize(
    "sending",
    [
        _sending(f"agent:{BOT_A}:cron:j:run:1", account=BOT_A),
        _sending("agent:main:cron:j:run:1", account="default"),
        _sending("agent:main:cron:j:run:1"),
        _sending(f"agent:{BOT_A}:connection:c:l:root", channel="webchat"),
    ],
    ids=["bots_own_account", "parent", "parent_no_account", "not_a_platform"],
)
def test_other_posts_are_sent_unchanged(tmp_path, sending):
    assert _run(tmp_path, [sending])["results"] == [{"result": None}]


def test_a_message_from_no_known_agent_is_refused(tmp_path):
    outcome = _run(tmp_path, [{"event": {"toolName": "message", "params": {"channel": "telegram"}}, "ctx": {}}])[
        "results"
    ][0]

    assert "error" in outcome
