import json
import os
from pathlib import Path

from hamcrest import assert_that, contains_string, equal_to, has_key

from api.tests.core.givenpy import given, then, when

_PLUGIN_DIR = (
    Path(__file__).parent.parent.parent
    / "domains"
    / "agents"
    / "scripts"
    / "openclaw"
    / "plugins"
    / "telemetry-push"
)


def test_plugin_index_js_exists():
    with given():
        with when("I check for the plugin entry point"):
            exists = (_PLUGIN_DIR / "index.js").exists()

        with then("the file exists"):
            assert_that(exists, equal_to(True))


def test_plugin_package_json_is_valid():
    with given():
        raw = (_PLUGIN_DIR / "package.json").read_text()

        with when("I parse package.json"):
            pkg = json.loads(raw)

        with then("it has the expected fields"):
            assert_that(pkg["name"], equal_to("telemetry-push"))
            assert_that(pkg["type"], equal_to("module"))


def test_plugin_openclaw_plugin_json_is_valid():
    with given():
        raw = (_PLUGIN_DIR / "openclaw.plugin.json").read_text()

        with when("I parse openclaw.plugin.json"):
            meta = json.loads(raw)

        with then("it has the expected id and activation"):
            assert_that(meta["id"], equal_to("telemetry-push"))
            assert_that(meta["activation"]["onStartup"], equal_to(True))


def test_index_js_reads_env_vars():
    with given():
        source = (_PLUGIN_DIR / "index.js").read_text()

        with when("I inspect the plugin source"):
            pass

        with then("it reads AGENT_ID, INGEST_URL, and INGEST_API_KEY"):
            assert_that(source, contains_string("AGENT_ID"))
            assert_that(source, contains_string("INGEST_URL"))
            assert_that(source, contains_string("INGEST_API_KEY"))


def test_index_js_registers_hooks():
    with given():
        source = (_PLUGIN_DIR / "index.js").read_text()

        with when("I inspect the plugin source"):
            pass

        with then("it registers message and tool call hooks"):
            assert_that(source, contains_string("message_received"))
            assert_that(source, contains_string("message_sent"))
            assert_that(source, contains_string("before_tool_call"))
            assert_that(source, contains_string("after_tool_call"))
            assert_that(source, contains_string("session_end"))


def test_overlay_includes_telemetry_push_in_plugins():
    with given():
        from api.domains.agents.builders import build_openclaw_config_overlay

        with when("I build a Slack overlay"):
            overlay = build_openclaw_config_overlay("litellm/qwen3", "http://x:4000")

        with then("telemetry-push is in the plugins allow list and entries"):
            assert_that("telemetry-push" in overlay["plugins"]["allow"], equal_to(True))
            assert_that(overlay["plugins"]["entries"], has_key("telemetry-push"))
            assert_that(
                overlay["plugins"]["entries"]["telemetry-push"]["enabled"],
                equal_to(True),
            )


def test_teams_overlay_includes_telemetry_push_in_plugins():
    with given():
        from api.domains.agents.builders import build_openclaw_config_overlay_teams

        with when("I build a Teams overlay"):
            overlay = build_openclaw_config_overlay_teams("litellm/qwen3", "http://x:4000")

        with then("telemetry-push is in the plugins allow list and entries"):
            assert_that("telemetry-push" in overlay["plugins"]["allow"], equal_to(True))
            assert_that(overlay["plugins"]["entries"], has_key("telemetry-push"))


def test_config_map_includes_telemetry_push_files():
    with given():
        from api.domains.agents.builders import build_config_map

        with when("I build an OpenClaw config map"):
            cm = build_config_map(
                agent_id=__import__("uuid").UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                org_id=__import__("uuid").UUID("11111111-2222-3333-4444-555555555555"),
                namespace="agent-farm",
                soul_md="# Soul",
                identity_md="# Identity",
                user_md="# User",
                tools_md="# Tools",
                agents_md="# Agents",
                boot_md="# Boot",
                bootstrap_md="# Bootstrap",
                heartbeat_md="# Heartbeat",
                openclaw_config_overlay={"plugins": {}},
            )

        with then("the config map has telemetry-push plugin files"):
            assert_that(cm.data, has_key("telemetry-push-index.js"))
            assert_that(cm.data, has_key("telemetry-push-package.json"))
            assert_that(cm.data, has_key("telemetry-push-plugin.json"))


def test_start_sh_installs_telemetry_push():
    with given():
        from api.domains.agents.builders import START_SH

        with when("I inspect the OpenClaw start.sh"):
            pass

        with then("it copies and installs the telemetry-push plugin"):
            assert_that(START_SH, contains_string("telemetry-push"))
