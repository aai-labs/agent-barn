"""Remove the managed messaging plugin; audit old jobs without replay or rerouting."""

import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

NATIVE_PLATFORMS = {"slack", "discord", "telegram", "teams"}


def usable_target(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "__agentbarn_no_home_channel__" not in value
        and not value.startswith("connection:")
    )


def retire(runtime: str, state: Path) -> dict:
    plugin = state / ("plugins" if runtime == "hermes" else "local-plugins") / "agentbarn-messaging"
    if plugin.is_symlink() or (plugin.exists() and not plugin.is_dir()):
        plugin.unlink()
    elif plugin.exists():
        shutil.rmtree(plugin)

    # Keep the spool as historical evidence. No SQLite read, drain, or receipt inference.
    report: dict = {"spool_present": (state / "agentbarn-messages.sqlite3").exists(), "jobs_requiring_repair": []}
    report["job_audit"] = "absent"
    config = {}
    if runtime == "openclaw":
        try:
            if (state / "openclaw.json").exists():
                config = json.loads((state / "openclaw.json").read_text())
                if not isinstance(config, dict) or not isinstance(config.get("channels", {}), dict):
                    raise TypeError("Invalid native config")
        except Exception:
            config = {}
            report["job_audit"] = "unreadable"
    stores = [state / "cron" / "jobs.json"]
    if runtime == "openclaw":
        stores.append(state / "state" / "openclaw.sqlite")
    for store in stores:
        try:
            if not store.exists():
                continue
            if store.suffix == ".sqlite":
                with closing(sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)) as db:
                    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'cron_jobs'").fetchone()
                    jobs = [row[0] for row in db.execute("SELECT job_json FROM cron_jobs")] if exists else []
            else:
                stored = json.loads(store.read_text())
                jobs = stored.get("jobs") if isinstance(stored, dict) else stored
            if not isinstance(jobs, list):
                raise TypeError("Invalid job store")
            for stored_job in jobs:
                try:
                    job = json.loads(stored_job) if store.suffix == ".sqlite" else stored_job
                    if not isinstance(job, dict):
                        raise TypeError("Invalid job")
                    if needs_repair(runtime, job, config):
                        job_id = str(job.get("id") or job.get("jobId") or "unknown")
                        report["jobs_requiring_repair"].append(
                            job_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) else "invalid-id"
                        )
                except Exception:
                    # Advisory audit failures cannot stop startup or hide later jobs.
                    report["job_audit"] = "unreadable"
            if report["job_audit"] != "unreadable":
                report["job_audit"] = "read"
        except Exception:
            report["job_audit"] = "unreadable"
    try:
        state.mkdir(parents=True, exist_ok=True)
        (state / "retired-messaging-audit.json").write_text(json.dumps(report) + "\n")
    except OSError:
        # The report is advisory; plugin removal above must still succeed.
        report["report_write"] = "failed"
    print(
        f"[messaging-retirement] spool_present={report['spool_present']} "
        f"job_audit={report['job_audit']} report_write={report.get('report_write', 'written')} "
        f"jobs_requiring_repair={len(report['jobs_requiring_repair'])}",
        flush=True,
    )
    return report


def needs_repair(runtime: str, job: dict, config: dict | None = None) -> bool:
    if job.get("enabled") is False:
        return False
    if runtime == "hermes":
        if job.get("state") in ("completed", "paused"):
            return False
        origin = job.get("origin")
        if isinstance(origin, dict) and not isinstance(origin.get("platform"), (str, type(None))):
            raise TypeError("Invalid origin platform")
        for deliver in str(job.get("deliver", "local")).split(","):
            platform, separator, target = deliver.strip().partition(":")
            if platform in NATIVE_PLATFORMS:
                if separator:
                    if not usable_target(target) or not usable_target(target.split(":", 1)[0]):
                        return True
                elif not usable_target(os.environ.get(f"{platform.upper()}_HOME_CHANNEL")):
                    return True
            elif (
                platform != "origin"
                or separator
                or not (
                    isinstance(origin, dict)
                    and origin.get("platform") in NATIVE_PLATFORMS
                    and usable_target(origin.get("chat_id"))
                )
            ):
                return True
        return False
    delivery = job.get("delivery")
    if delivery is None and job.get("sessionTarget") == "main":
        return False
    if not isinstance(delivery, dict):
        if delivery is not None:
            raise TypeError("Invalid delivery")
        return True
    if delivery.get("mode") == "none":
        return False
    channel = delivery.get("channel")
    if channel is None:
        return True
    if not isinstance(channel, str):
        raise TypeError("Invalid delivery channel")
    if channel not in {"slack", "discord", "telegram", "msteams"}:
        return True
    target = delivery.get("to")
    if target is None or (isinstance(target, str) and not target.strip()):
        native_channel = (config or {}).get("channels", {}).get(channel, {})
        if not isinstance(native_channel, dict) or native_channel.get("enabled") is False:
            return True
        target = native_channel.get("defaultTo")
    return not usable_target(target)


if __name__ == "__main__":
    retire(sys.argv[1], Path(sys.argv[2]))
