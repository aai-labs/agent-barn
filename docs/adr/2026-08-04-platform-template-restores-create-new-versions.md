# Platform Template restores create new versions

Status: Accepted
Date: 2026-08-04
Origin: AF-183 (Platform Template draft/publish)

Platform Administrators can inspect any immutable published Platform Template Version and seed the current Draft Template Version from a selected historical version. Publishing that Template Restore always creates the next immutable version instead of changing an active-version pointer or mutating history; this preserves Agent pins, auditability, and the existing version-resolution model while allowing a bad version to be rolled back operationally.

## Consequences

- Restoring v1 after v2 produces v3 with v1's content; v1 and v2 remain available in history.
- Existing Agents pinned to v2 remain on v2 until explicitly repinned.
- A repair draft can be based on any selected historical version while the restored version serves as the latest platform version.
