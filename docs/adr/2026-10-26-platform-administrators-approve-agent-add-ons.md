# Platform Administrators approve Agent Add-ons

Status: Accepted
Date: 2026-10-26

An Organization Owner or Admin may ask for extra libraries or tools on one of its Agents (a Python library, say, or a command-line tool like aai-cli), giving the exact thing to install, such as a pinned package or a `git clone` at a commit. A Platform Administrator approves that exact request before it reaches the Agent, because what runs on the cluster must be reviewed and arbitrary Dockerfiles are not allowed there. The Hermes and OpenClaw runtimes stay the only images.

This is a narrow exception to [Platform Oversight without Organization access](2026-07-30-platform-oversight-without-organization-access.md), separate from the one [Agent Sizes](2026-10-22-platform-administrators-set-an-agents-size.md) made: that one does not extend to add-ons, and this one does not extend to sizes or restarts. It is also a deliberate, reviewed exception to [the Integration Plugin seam](2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md), under which plugins are trusted release artifacts rather than dynamically installed packages: an add-on is installed per Agent at start, from outside a release, but only after a Platform Administrator has approved exactly what it asks to install.

## Considered alternatives

Building a custom image per request would need an in-cluster image builder and would put arbitrary Dockerfiles on the cluster, which the platform does not allow. Letting an Organization install whatever it likes into the Agent's own volume needs no review at all, which is what the platform wants to avoid. Approving a package name without its version, commit or checksum would let the add-on itself change after the review.

## Consequences

- A Platform Administrator may approve, reject (with a reason) and revoke add-on requests for an Organization's Agent, from Platform View, without a Membership. A request is never edited: to change one, reject it and the Organization files a new one.
- A Platform Administrator may read a request's contents (the kind, name, version, URL, commit, checksum or command, and why), which reviewing it needs, and the names that place it (Organization, Agent, runtime, requester). Nothing else of the Agent: no prompts, logs, Secrets or configuration, and no lifecycle control. A decision never starts, stops or restarts the Agent; it applies at the Agent's next start.
- Requesting an add-on is limited to Organization Owners and Admins (`agent.addon.manage`); no Agent Access Role grants it.
- An approved add-on installs in an init container that holds no credentials, into a volume the Agent can use but not change.
- Only what a request names is pinned. A pip or npm add-on's dependencies are resolved again at every install, so a reinstall can bring dependency versions the reviewer did not see; [Agent Add-ons](../features/agent-addons.md#installation) says which.
- Each request and decision is an Organization-scoped Security Audit Record carrying the request's content, with the administrator's user as actor when they have no Membership there.
- Any further platform write on Organization-owned resources still needs its own decision.
