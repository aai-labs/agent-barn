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
