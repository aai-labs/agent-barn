# Scheduled snapshots capture a running Agent's volume live

Status: Accepted
Date: 2026-10-27
Origin: AF-401

Each running Agent gets a restore point on a schedule, so a user can go back to just before they broke something. The schedule captures the volume while the Agent keeps running, with the same tar Job as a manual capture, mounted read-only and placed on the Agent pod's node. Stopping the Agent for each snapshot would cost minutes of downtime and missed messages several times a day, and on a namespace at its quota a stopped Agent can lose its slot to another one.

## Consequences

- A live snapshot is a copy of files as they were while being read, not of one instant. A file deleted mid-capture is left out; one that shrank is padded to the size its header promised, and the manifest counts it as `changed`. A database being written (OpenClaw's `state/openclaw.sqlite` and its WAL, the trigger receipts) can be caught half-written. A restore puts such a file back as it was read.
- Manual captures and restores still require a stopped Agent; nothing about them changes.
- A scheduled snapshot in progress blocks no other operation. A capture or a restore that needs the volume stops it first.
- Revisit if restores from scheduled snapshots turn out to bring back broken databases: the next step is copying SQLite files through SQLite's own backup API inside the capture Job.
