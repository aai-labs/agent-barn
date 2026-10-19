# Custom API integration evidence

Captured from the branch UI with Chromium at a 1440px viewport using the
existing Playwright `CustomApiPage` and `CustomApiDataSupport` fixtures. All
connection data and credentials are test fixtures; no live upstream API is used.

- [Connection editor](connection-editor.png): API-key header authentication,
  retained hidden token and secret header, and credential isolation staged on a
  running Agent.
- [Restart confirmation](restart-confirmation.png): explicit confirmation before
  applying the staged mode and restarting.
- [Rejected bulk save](rejected-bulk-save.png): colliding identifiers are rejected
  and both drafts remain visible. The capture scenario also asserts that no
  lifecycle request was sent. API integration tests independently prove that a
  conflicting batch leaves persisted connections and a running Agent unchanged.

The rejection screenshot uses a deterministic mocked validation response. It
demonstrates the editor's error handling, rather than live end-to-end validation.
