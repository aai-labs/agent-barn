"""The install-addons script's own contract, run as a subprocess with no network.

What it installs with pip, npm and git is proven inside the real runtime images by the
runtime contract tests. Here: it caches by hash, wipes and reinstalls when the hash moves,
installs a checksummed binary and a reviewed command, and on a failure names the add-on in its
termination message, leaves no marker, and exits non-zero.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_

from api.domains.agents.builders.addons import INSTALL_ADDONS_PY
from api.tests.core.givenpy import given, then, when

_COMMAND_ID = "01a1795e-0cc7-72ff-897d-4f2780e7b5d1"
_BINARY_ID = "01a1795e-0cc7-72ff-897d-4f2780e7b5d2"


@dataclass
class _Run:
    returncode: int
    output: str
    termination: dict | None


def install_root_is_ready(tmp_path: Path):
    def step(context):
        context.root = tmp_path
        context.addons = tmp_path / "addons"
        context.addons.mkdir()
        context.config = tmp_path / "config"
        context.config.mkdir()
        (context.config / "install-addons.py").write_text(INSTALL_ADDONS_PY)
        context.counter = tmp_path / "command-runs"
        context.counter.write_text("")

    return step


def a_downloadable_binary(content: bytes = b"#!/bin/sh\necho drawn\n"):
    def step(context):
        context.binary = context.root / "drawtool-download"
        context.binary.write_bytes(content)
        context.binary_sha = hashlib.sha256(content).hexdigest()

    return step


def _command_addon(context, command: str | None = None) -> dict:
    return {
        "id": _COMMAND_ID,
        "kind": "command",
        "name": "marker",
        "command": command
        or f'echo run >> {context.counter} && echo hello > "$ADDONS_DIR/bin/hello" && chmod +x "$ADDONS_DIR/bin/hello"',
    }


def _binary_addon(context, sha256: str | None = None) -> dict:
    return {
        "id": _BINARY_ID,
        "kind": "binary",
        "name": "drawtool",
        "url": context.binary.as_uri(),
        "sha256": sha256 or context.binary_sha,
    }


def run_install(context, addons: list[dict], plan_hash: str = "hash-1") -> _Run:
    (context.config / "addons.json").write_text(
        json.dumps({"hash": plan_hash, "timeout_seconds": 600, "addons": addons})
    )
    termination = context.root / "termination-log"
    termination.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, str(context.config / "install-addons.py")],
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "ADDONS_DIR": str(context.addons),
            "ADDONS_TERMINATION_LOG": str(termination),
            # Stands in for anything the container might carry; an install must not see it.
            "SECRET_FROM_PARENT": "leaked",
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return _Run(
        result.returncode,
        result.stdout + result.stderr,
        json.loads(termination.read_text()) if termination.exists() else None,
    )


def _runs(context) -> int:
    return context.counter.read_text().count("run")


def test_a_command_and_a_checksummed_binary_install_and_the_marker_is_written_last(tmp_path) -> None:
    assert shutil.which("bash"), "bash is required"
    with given([install_root_is_ready(tmp_path), a_downloadable_binary()]) as context:
        with when("the approved add-ons are installed"):
            result = run_install(context, [_command_addon(context), _binary_addon(context)])

        with then("both are in place and the marker holds the plan's hash"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that((context.addons / "bin" / "hello").read_text(), equal_to("hello\n"))
            installed = context.addons / "bin" / "drawtool"
            assert_that(installed.read_bytes(), equal_to(context.binary.read_bytes()))
            assert_that(installed.stat().st_mode & 0o111, equal_to(0o111))
            assert_that((context.addons / ".agentbarn-addons-hash").read_text().strip(), equal_to("hash-1"))


def test_an_unchanged_plan_installs_nothing_again(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        run_install(context, [_command_addon(context)])

        with when("the Agent starts again on the same plan"):
            result = run_install(context, [_command_addon(context)])

        with then("the install is skipped"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that(result.output, contains_string("nothing to do"))
            assert_that(_runs(context), equal_to(1))


def test_a_new_hash_wipes_the_volume_and_installs_everything_again(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path), a_downloadable_binary()]) as context:
        run_install(context, [_command_addon(context), _binary_addon(context)])

        with when("the binary is revoked, which moves the hash"):
            result = run_install(context, [_command_addon(context)], plan_hash="hash-2")

        with then("what is no longer approved is gone and the rest is installed again"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that((context.addons / "bin" / "drawtool").exists(), is_(False))
            assert_that((context.addons / "bin" / "hello").exists(), is_(True))
            assert_that(_runs(context), equal_to(2))


def test_a_new_hash_wipes_what_an_installer_left_read_only(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        # Go's module cache is written read-only; nothing in a read-only directory can be deleted.
        read_only_cache = _command_addon(
            context,
            f'echo run >> {context.counter} && mkdir -p "$HOME/go/pkg/mod/example" '
            '&& echo module > "$HOME/go/pkg/mod/example/go.mod" && chmod -R a-w "$HOME/go"',
        )
        run_install(context, [read_only_cache])

        with when("the hash moves"):
            result = run_install(context, [_command_addon(context)], plan_hash="hash-2")

        with then("the read-only tree is removed and the new plan installs"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that((context.addons / "home" / "go").exists(), is_(False))
            assert_that((context.addons / "bin" / "hello").exists(), is_(True))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can remove anything, so the volume cannot be made uncleared")
def test_a_volume_that_cannot_be_cleared_fails_the_install_naming_no_add_on(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        run_install(context, [_command_addon(context)])
        context.addons.chmod(0o555)
        try:
            with when("the hash moves but the volume's own entries cannot be removed"):
                result = run_install(context, [_command_addon(context)], plan_hash="hash-2")

            with then("the install fails with a report naming no add-on, so the API keeps its log"):
                assert_that(result.returncode, equal_to(1))
                assert_that(result.termination, equal_to({"addon_id": "", "reason": "failed"}))
                assert_that(result.output, contains_string("could not clear the add-ons volume"))
        finally:
            context.addons.chmod(0o755)


def test_a_checksum_mismatch_fails_the_install_naming_the_add_on(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path), a_downloadable_binary()]) as context:
        with when("the download does not match the approved SHA-256"):
            result = run_install(context, [_binary_addon(context, sha256="0" * 64)])

        with then("the install fails, says which add-on and why, and installs nothing"):
            assert_that(result.returncode, equal_to(1))
            assert_that(result.termination, equal_to({"addon_id": _BINARY_ID, "reason": "checksum"}))
            assert_that(result.output, contains_string("FAILED: drawtool"))
            assert_that((context.addons / "bin" / "drawtool").exists(), is_(False))
            assert_that((context.addons / ".agentbarn-addons-hash").exists(), is_(False))


def test_a_failing_command_fails_the_install_and_the_next_start_retries(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        failing = _command_addon(context, f"echo run >> {context.counter} && false")

        with when("the reviewed command fails"):
            result = run_install(context, [failing])

        with then("the install fails naming it, and no marker is left"):
            assert_that(result.returncode, equal_to(1))
            assert_that(result.termination, equal_to({"addon_id": _COMMAND_ID, "reason": "failed"}))
            assert_that((context.addons / ".agentbarn-addons-hash").exists(), is_(False))

        with when("the Agent starts again"):
            run_install(context, [failing])

        with then("the install runs again rather than trusting a half-finished volume"):
            assert_that(_runs(context), equal_to(2))


def test_a_command_runs_with_a_strict_shell_and_no_inherited_environment(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        command = _command_addon(
            context,
            'echo "${SECRET_FROM_PARENT:-unset} $HOME" > "$ADDONS_DIR/bin/env-seen"; undefined_variable_is_fatal=$NOPE',
        )

        with when("a command reads the environment and then an unset variable"):
            result = run_install(context, [command])

        with then("nothing from outside reached it, HOME was the volume's, and the unset variable failed it"):
            assert_that(result.returncode, equal_to(1))
            seen = (context.addons / "bin" / "env-seen").read_text()
            assert_that(seen.split()[0], equal_to("unset"))
            assert_that(seen.split()[1], equal_to(str(context.addons / "home")))


def test_a_command_that_installs_nothing_into_the_volume_fails_naming_the_add_on(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        scratch_only = _command_addon(context, 'echo tool > tool && echo tool > "$TMPDIR/tool"')

        with when("the reviewed command exits 0 having written only to its working directory and TMPDIR"):
            result = run_install(context, [scratch_only])

        with then("the install fails naming it and saying where an install must go, and no marker is left"):
            assert_that(result.returncode, equal_to(1))
            assert_that(result.termination, equal_to({"addon_id": _COMMAND_ID, "reason": "failed"}))
            assert_that(result.output, contains_string("installed nothing into $HOME or $ADDONS_DIR"))
            assert_that((context.addons / ".agentbarn-addons-hash").exists(), is_(False))


def test_a_command_that_only_rewrites_a_file_already_in_the_volume_counts_as_installing(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        writes = _command_addon(context, 'printf "#!/bin/sh\\n" > "$ADDONS_DIR/bin/tool"')
        rewrites = {
            **_command_addon(context, 'printf "#!/bin/sh\\necho v2\\n" > "$ADDONS_DIR/bin/tool"'),
            "id": _BINARY_ID,
            "name": "tool-v2",
        }

        with when("a second command changes only what the first one installed"):
            result = run_install(context, [writes, rewrites])

        with then("both install"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that((context.addons / "bin" / "tool").read_text(), contains_string("v2"))


def _home_installer(tool_dir: str, *names: str) -> str:
    """A stand-in for a `curl | bash` installer: executables under HOME, a PATH line in .bashrc."""
    writes = " && ".join(
        f'printf "#!/bin/sh\\necho {name}\\n" > "$HOME/{tool_dir}/{name}" && chmod +x "$HOME/{tool_dir}/{name}"'
        for name in names
    )
    return f'mkdir -p "$HOME/{tool_dir}" && {writes} && echo "export PATH=$HOME/{tool_dir}:$PATH" >> "$HOME/.bashrc"'


def test_a_command_installing_into_home_has_its_executables_linked_into_bin(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        opencode = {**_command_addon(context, _home_installer(".opencode/bin", "opencode")), "name": "opencode"}
        solana = {
            **_command_addon(context, _home_installer(".local/share/solana/install/active_release/bin", "solana")),
            "id": _BINARY_ID,
            "name": "solana",
        }

        with when("two installers that put their executables under HOME are installed"):
            result = run_install(context, [opencode, solana])

        with then("both stay in the volume and run from bin, through links that resolve wherever it is mounted"):
            assert_that(result.returncode, equal_to(0), result.output)
            for name in ("opencode", "solana"):
                link = context.addons / "bin" / name
                assert_that(link.is_symlink(), is_(True))
                assert_that(Path(link.readlink()).is_absolute(), is_(False))
                ran = subprocess.run([str(link)], capture_output=True, text=True, check=True)
                assert_that(ran.stdout.strip(), equal_to(name))


def test_an_executable_under_home_never_shadows_the_image_or_replaces_what_bin_has(tmp_path) -> None:
    with given([install_root_is_ready(tmp_path)]) as context:
        command = _command_addon(
            context,
            'printf "#!/bin/sh\\necho mine\\n" > "$ADDONS_DIR/bin/tool" && '
            + _home_installer(".local/bin", "tool", "sh", "fresh"),
        )

        with when("an installer puts a name bin already has, and one the image has, under HOME"):
            result = run_install(context, [command])

        with then("only the new name is linked; the image's and bin's own are left alone"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that((context.addons / "bin" / "fresh").is_symlink(), is_(True))
            assert_that((context.addons / "bin" / "sh").exists(), is_(False))
            assert_that(result.output, contains_string("not linking sh"))
            assert_that((context.addons / "bin" / "tool").is_symlink(), is_(False))
            assert_that((context.addons / "bin" / "tool").read_text(), contains_string("mine"))
