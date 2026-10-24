# AF-415 UI evidence

Captured 2026-10-22 from the repository Chromium scenarios in
`ui/tests/e2e/artifacts.spec.ts` (3 passed). All Agent identities, file metadata,
workflow state and download responses are synthetic browser fixtures. These
screenshots do not demonstrate a live Agent, Garage deployment or provider send.

- [Agent Files](agent-files.png): a user with agent.read can see metadata and request a fresh download link.
- [Run attachments](run-files.png): published files alongside the existing final text summary.
- [Step attachments](step-files.png): the selected step's files alongside its text summary.

Temporary screenshot capture instrumentation was removed after capture; production
code and the browser assertions are unchanged.

## Persistent deployment path (2026-10-23)

[persistent-files-live.png](persistent-files-live.png) comes from real local sign-in
and Agent Files without route/download interception. Both runtime images uploaded
actual bytes through the API, persistent Compose Garage was recreated, and the
browser downloaded the exact bytes three times. Identity/database and external
integration adapters are isolated test fixtures; no live model/provider send or
installation deployment is shown. The source probe is
`api/runtime_tests/test_artifact_deployment.py`.
