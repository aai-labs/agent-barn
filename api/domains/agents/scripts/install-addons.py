"""Install an Agent's approved add-ons into its add-ons volume.

Runs as the `install-addons` init container, as the runtime's non-root user, with the
add-ons volume at $ADDONS_DIR and its plan (`addons.json`) beside this script. It has no
credentials of any kind, by design.

The plan carries a hash of the runtime image and the approved add-ons. When the volume's
marker already holds that hash, everything is installed and the script exits at once.
Otherwise it wipes the volume, installs every add-on in order, and writes the marker last, so
an install that fails or is cut short is redone from the start next time.

If an add-on fails, the script writes `{"addon_id": ..., "reason": ...}` to the container's
termination message, which is how the API learns which one, and exits non-zero, which fails
the start. Its output is the install log the Organization sees.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ADDONS_DIR = Path(os.environ.get("ADDONS_DIR", "/opt/addons"))
PLAN = Path(__file__).with_name("addons.json")
MARKER = ADDONS_DIR / ".agentbarn-addons-hash"
TERMINATION_LOG = Path(os.environ.get("ADDONS_TERMINATION_LOG", "/dev/termination-log"))
# Left for the script to report a timeout itself, before the container's `timeout` kills it.
DEADLINE_MARGIN_SECONDS = 20
DOWNLOAD_CHUNK = 1024 * 1024
# HOME for command add-ons. It is in the volume, so what an installer puts in HOME (as most
# `curl | bash` installers do) is kept, and its executables are linked into bin.
COMMAND_HOME = ADDONS_DIR / "home"
# Where installers put their executables under HOME, relative to it.
HOME_BIN_PATTERNS = (
    "bin",
    ".local/bin",
    ".*/bin",
    ".local/share/*/bin",
    ".local/share/solana/install/active_release/bin",
)


class AddonFailed(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def log(message: str) -> None:
    print(f"[install-addons] {message}", flush=True)


def report_failure(addon_id: str, reason: str) -> None:
    try:
        TERMINATION_LOG.write_text(json.dumps({"addon_id": addon_id, "reason": reason}))
    except OSError:
        log("could not write the termination message")


def volume_files() -> dict[str, tuple[int, int]]:
    """Every file and link in the volume, by path, with its size and modification time."""
    files = {}
    for root, dirs, names in os.walk(ADDONS_DIR):
        dirs[:] = [d for d in dirs if not (root == str(ADDONS_DIR) and d == "lost+found")]
        for entry in [*names, *(d for d in dirs if os.path.islink(os.path.join(root, d)))]:
            path = os.path.join(root, entry)
            stat = os.lstat(path)
            files[path] = (stat.st_size, stat.st_mtime_ns)
    return files


def link_home_executables() -> None:
    """Link the executables command add-ons installed under HOME into bin, so they are on PATH.

    The links are relative, so they resolve wherever the volume is mounted. Nothing in bin is
    replaced, and a name the runtime image already has (node, python3, git) is left alone:
    bin comes ahead of the image's PATH, and the runtime runs those.
    """
    image_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    bin_dir = ADDONS_DIR / "bin"
    seen = set()
    for pattern in HOME_BIN_PATTERNS:
        for directory in sorted(COMMAND_HOME.glob(pattern)):
            if not directory.is_dir() or directory.resolve() in seen:
                continue
            seen.add(directory.resolve())
            for executable in sorted(directory.iterdir()):
                if not executable.is_file() or not os.access(executable, os.X_OK):
                    continue
                link = bin_dir / executable.name
                if link.exists() or link.is_symlink():
                    continue
                if shutil.which(executable.name, path=image_path):
                    log(f"not linking {executable.name}: the runtime image has its own")
                    continue
                link.symlink_to(os.path.relpath(executable, bin_dir))
                log(f"linked {executable.name} -> {executable}")


def wipe() -> None:
    for entry in ADDONS_DIR.iterdir():
        # A volume formatted as ext4 keeps lost+found, which belongs to root.
        if entry.name == "lost+found":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


class Installer:
    def __init__(self, deadline: float, work: Path) -> None:
        self.deadline = deadline
        self.work = work
        home = work / "home"
        home.mkdir()
        # Only what the tools need. Nothing is inherited beyond PATH: there is nothing secret
        # in this container, and an install should not depend on what happens to be set.
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(work),
            "UV_CACHE_DIR": str(work / "uv-cache"),
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "npm_config_cache": str(work / "npm-cache"),
            "npm_config_update_notifier": "false",
            "npm_config_fund": "false",
            "npm_config_audit": "false",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "ADDONS_DIR": str(ADDONS_DIR),
        }
        self.constraints: Path | None = None

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise AddonFailed("timeout", "the install ran out of time")
        return left

    def run(self, command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
        log("$ " + " ".join(command))
        try:
            result = subprocess.run(
                command,
                cwd=cwd or self.work,
                env=env or self.env,
                stdin=subprocess.DEVNULL,
                stdout=sys.stdout,
                stderr=subprocess.STDOUT,
                timeout=self.remaining(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise AddonFailed("timeout", "the install ran out of time") from None
        except OSError as exc:
            raise AddonFailed("failed", f"could not run {command[0]}: {exc}") from None
        if result.returncode != 0:
            raise AddonFailed("failed", f"{command[0]} exited with {result.returncode}")

    def runtime_constraints(self) -> Path:
        """The packages the runtime's own Python already has, pinned at their versions.

        Add-ons are importable alongside the runtime (PYTHONPATH), so a dependency installed
        at another version could shadow the runtime's own. Installing against these pins makes
        such an add-on fail here, by name, instead.
        """
        if self.constraints is None:
            path = self.work / "runtime-constraints.txt"
            frozen = subprocess.run(
                ["uv", "pip", "freeze", "--python", sys.executable],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=min(60.0, self.remaining()),
                check=False,
            )
            pins = [line for line in frozen.stdout.splitlines() if "==" in line and not line.startswith(("-", "#"))]
            path.write_text("\n".join(pins) + "\n")
            self.constraints = path
        return self.constraints

    def pip(self, addon: dict) -> None:
        self.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--target",
                str(ADDONS_DIR / "python"),
                "--constraint",
                str(self.runtime_constraints()),
                f"{addon['name']}=={addon['version']}",
            ]
        )

    def npm(self, addon: dict) -> None:
        self.run(
            [
                "npm",
                "install",
                "--global",
                "--prefix",
                str(ADDONS_DIR / "node"),
                f"{addon['name']}@{addon['version']}",
            ]
        )

    def git(self, addon: dict) -> None:
        target = ADDONS_DIR / "src" / addon["name"]
        commit = addon["commit"]
        no_hooks = ["-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never"]
        self.run(["git", *no_hooks, "init", "--quiet", str(target)])
        self.run(["git", *no_hooks, "-C", str(target), "remote", "add", "origin", addon["url"]])
        try:
            # Most hosts serve one commit by its SHA; it saves fetching the whole history.
            self.run(["git", *no_hooks, "-C", str(target), "fetch", "--quiet", "--depth", "1", "origin", commit])
        except AddonFailed as exc:
            if exc.reason == "timeout":
                raise
            log("the host would not serve the commit on its own; fetching the whole repository")
            self.run(["git", *no_hooks, "-C", str(target), "fetch", "--quiet", "origin"])
        self.run(["git", *no_hooks, "-C", str(target), "checkout", "--quiet", "--detach", commit])
        head = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"], env=self.env, capture_output=True, text=True, check=False
        ).stdout.strip()
        if head != commit:
            raise AddonFailed("failed", f"checked out {head or 'nothing'}, not {commit}")

    def binary(self, addon: dict) -> None:
        target = ADDONS_DIR / "bin" / addon["name"]
        partial = self.work / f"{addon['name']}.download"
        log(f"downloading {addon['url']}")
        digest = hashlib.sha256()
        request = urllib.request.Request(addon["url"], headers={"User-Agent": "agentbarn-install-addons"})
        try:
            with (
                urllib.request.urlopen(request, timeout=min(60.0, self.remaining())) as response,
                partial.open("wb") as out,
            ):
                while chunk := response.read(DOWNLOAD_CHUNK):
                    self.remaining()
                    digest.update(chunk)
                    out.write(chunk)
        except AddonFailed:
            raise
        except Exception as exc:
            raise AddonFailed("failed", f"the download failed: {exc}") from None
        actual = digest.hexdigest()
        if actual != addon["sha256"]:
            raise AddonFailed("checksum", f"the download's SHA-256 is {actual}, not {addon['sha256']}")
        shutil.move(partial, target)
        target.chmod(0o755)
        log(f"SHA-256 matches; installed {target}")

    def command(self, addon: dict) -> None:
        # Exactly the reviewed text, in a fresh directory with nothing of the Agent in reach.
        # HOME is the volume's, shared by every command add-on in order.
        workdir = Path(tempfile.mkdtemp(dir=self.work))
        before = volume_files()
        self.run(
            ["bash", "-euo", "pipefail", "-c", addon["command"]],
            cwd=workdir,
            env={**self.env, "HOME": str(COMMAND_HOME)},
        )
        # The working directory is thrown away, so an installer that writes only there or to
        # /tmp leaves the Agent nothing.
        if volume_files() == before:
            raise AddonFailed(
                "failed",
                "the command installed nothing into $HOME or $ADDONS_DIR; the working directory and /tmp are discarded",
            )


def main() -> int:
    plan = json.loads(PLAN.read_text())
    wanted = plan["hash"]
    if MARKER.is_file() and MARKER.read_text().strip() == wanted:
        log(f"{len(plan['addons'])} add-on(s) already installed; nothing to do")
        return 0

    deadline = time.monotonic() + max(int(plan.get("timeout_seconds", 600)) - DEADLINE_MARGIN_SECONDS, 30)
    log("installing add-ons from scratch")
    wipe()
    for directory in ("python", "node", "src", "bin", "home"):
        (ADDONS_DIR / directory).mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="install-addons-") as scratch:
        installer = Installer(deadline, Path(scratch))
        for addon in plan["addons"]:
            log(f"--- {addon['kind']} {addon['name']}")
            try:
                getattr(installer, addon["kind"])(addon)
            except AddonFailed as exc:
                log(f"FAILED: {addon['name']}: {exc}")
                report_failure(addon["id"], exc.reason)
                return 1
            except Exception as exc:
                log(f"FAILED: {addon['name']}: {type(exc).__name__}: {exc}")
                report_failure(addon["id"], "failed")
                return 1
            log(f"installed {addon['name']}")

    link_home_executables()
    MARKER.write_text(wanted + "\n")
    log(f"{len(plan['addons'])} add-on(s) installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
