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
    if plugin.is_symlink():
        plugin.unlink()
    elif plugin.exists():
        shutil.rmtree(plugin)

    # Keep the spool as historical evidence. No SQLite read, drain, or receipt inference.
    report: dict = {"spool_present": (state / "agentbarn-messages.sqlite3").exists(), "jobs_requiring_repair": []}
    report["job_audit"] = "absent"
    stores = [state / "cron" / "jobs.json"]
    if runtime == "openclaw":
        stores.append(state / "state" / "openclaw.sqlite")
    for store in stores:
        if not store.exists():
            continue
        try:
            if store.suffix == ".sqlite":
                with closing(sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)) as db:
                    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'cron_jobs'").fetchone()
                    jobs = (
                        [json.loads(row[0]) for row in db.execute("SELECT job_json FROM cron_jobs")] if exists else []
                    )
            else:
                stored = json.loads(store.read_text())
                jobs = stored.get("jobs") if isinstance(stored, dict) else stored
            if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
                raise ValueError("Invalid job store")
            for job in jobs:
                if needs_repair(runtime, job):
                    job_id = str(job.get("id") or job.get("jobId") or "unknown")
                    report["jobs_requiring_repair"].append(
                        job_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) else "invalid-id"
                    )
            if report["job_audit"] != "unreadable":
                report["job_audit"] = "read"
        except (OSError, ValueError, sqlite3.Error):
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


def needs_repair(runtime: str, job: dict) -> bool:
    if runtime == "hermes":
        origin = job.get("origin")
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
    if not isinstance(delivery, dict):
        return True
    if delivery.get("mode") == "none":
        return False
    return delivery.get("channel") not in {"slack", "discord", "telegram", "msteams"} or not usable_target(
        delivery.get("to")
    )


if __name__ == "__main__":
    retire(sys.argv[1], Path(sys.argv[2]))
