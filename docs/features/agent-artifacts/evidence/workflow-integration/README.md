# Workflow artifact UI evidence

Actual Chromium captures of the workflow integration after rebasing onto staging
`57bbefd0f`, with feature implementation `390cd534a`. Captured 2026-10-29 at a
1600px viewport. API interception supplies fixture identity, file metadata,
checkpoint summaries and successful run state; these are not live model/session
or storage screenshots. The real-image byte and persistent-storage contracts are
recorded separately in [verification evidence](../../EVIDENCE.md).

- [Run inputs](run-inputs.png): existing-file selection, upload and removable attachment.
- [Step files](step-files.png): one selected panel groups summary, file handoff and timing.
- [Final result](final-result.png): the last accepted checkpoint's downloadable deliverable.
- [All artifacts](all-artifacts.png): separate run collection with step/final roles.

The PR description embeds these images using commit-pinned links. Visible
checksums are omitted; immutable identities and byte verification remain internal.
