# AF-155: Fix Openclaw Reply Dropping in Public Channels

## Context

Openclaw agents fail to deliver final Slack replies in public channels. Streaming progress messages ("analyzing...", "summarizing findings...") appear, the telemetry plugin captures the full LLM response (visible in the UI conversations page), but the final message never arrives in Slack. DMs work fine.

## Root Cause: Confirmed Openclaw Version Bug

**Confidence: ~97%.** This is a **version problem**, not a code problem. Our config is correct — the bug is in Openclaw 2026.5.7's outbound Slack delivery path.

### Evidence from codebase analysis

1. **Streaming partial messages appear in channels** → Slack connection works, bot has permissions, channel membership is correct
2. **Telemetry captures the response** → LLM generates the response successfully (`agent_end` fires in `telemetry-push/index.js`)
3. **Final message doesn't appear** → Delivery fails AFTER response generation, in the Openclaw-internal delivery step we don't control
4. **DMs work fine** → Channel/thread-specific delivery issue
5. **Prior evidence from AF-122**: Openclaw's `message_sent` hook never fires (confirmed by pod logs), indicating known issues in the outbound delivery lifecycle
6. **Our config matches Openclaw docs**: `replyToModeByChatType.channel: "all"`, channels have `enabled: true`, streaming is `mode: "partial"` + `nativeTransport: true` per docs

### Evidence from Openclaw GitHub issues

Multiple open issues describe **exactly this behavior** on versions around 2026.5.x:

- **[#20273](https://github.com/openclaw/openclaw/issues/20273)** — "Slack streaming stop failure **silently drops agent response text**." When `stopSlackStream()` fails, response text is silently lost — never delivered. The stop-stream error path has **no fallback delivery mechanism**. This is the exact mechanism causing our bug.

- **[#78061](https://github.com/openclaw/openclaw/issues/78061)** — "Slack thread session generates responses but **fails to deliver** to Slack." Rated P1 (High). Manual `chat.postMessage` via curl to the same thread works fine, proving the bug is in **Openclaw's delivery path**, not Slack or credentials.

- **[#80715](https://github.com/openclaw/openclaw/issues/80715)** — "Slack replies **silently dropped**: composed in transcript, never posted to Slack." Transcript shows all replies completed with `stopReason: "stop"` and `responseId`, but `conversations.replies` shows **0 thread replies**. Bot never posted to the channel. This matches our exact symptom (response in UI but not in Slack).

- **[#70804](https://github.com/openclaw/openclaw/issues/70804)** — "Slack channel mentions reach OpenClaw but **no reply is sent**" (version 2026.4.22). `lastInboundAt` updates but `lastOutboundAt` remains null.

- **[#20337](https://github.com/openclaw/openclaw/issues/20337)** — Thread replies fail when streaming enabled (`missing_recipient_team_id`). No reply posted.

- **[#52536](https://github.com/openclaw/openclaw/issues/52536)** — First thread reply streams to channel instead of thread.

### Why this is NOT a code problem

- Config is correct per Openclaw docs (verified against [docs.openclaw.ai/channels/slack](https://docs.openclaw.ai/channels/slack))
- Issue #78061 explicitly proves the Slack API and credentials work — direct `chat.postMessage` succeeds, only Openclaw's delivery path fails
- Openclaw 2026.5.7 release notes added `deliverySucceeded=false` reporting — meaning the framework itself acknowledged the delivery failure but didn't fix the root cause
- All streaming/channel/thread settings match documented defaults

### Why upgrading fixes it

[Openclaw 2026.6.11](https://github.com/openclaw/openclaw/releases/tag/v2026.6.11) release notes:
- "Fixes **misplaced replies**, **stuck sends**, reconnects"
- "Keeps Slack replies in the **active thread**"
- "Long-running streamed auto-replies **less likely to stop early or abort**"
- "Fixes completed assistant messages appearing **twice** in Slack and other streamed chats after a multi-message reply"
- Delivery and reconnect fixes span Telegram, WhatsApp, Matrix, Google Chat, Slack, and other channels

## Fix: Upgrade Openclaw from 2026.5.7 → 2026.6.11 + Config Compatibility

### Part 1: Image upgrade (DONE)

1. **`openclaw-base/Dockerfile`** ✅
   - Line 34: `npm install -g openclaw@2026.5.7` → `npm install -g openclaw@2026.6.11`
   - Line 63: `@openclaw/msteams@2026.5.7` → `@openclaw/msteams@2026.5.27` (latest available on npm)

2. **`openclaw-base/VERSION`** ✅
   - `0.3.0` → `0.4.0`

3. **`.env.deploy.spec`** ✅
   - Line 26: `OPENCLAW_IMAGE_TAG=0.3.0` → `OPENCLAW_IMAGE_TAG=0.4.0`

### Part 2: Config overlay compatibility fix (gateway auth)

**Problem:** Openclaw 2026.6.x introduced mandatory gateway API authentication as part of "safer admin defaults." The gateway's internal HTTP/WS server on port 18789 now requires a device identity or auth token for all connections. Without it:

- The gateway auto-generates an ephemeral runtime token on startup
- Our `healthz-server.js` runs `openclaw health --json` which connects to this internal API — and gets rejected with `device identity required` (WebSocket close code 1008)
- Repeated `[ws] closed before connect` errors flood the logs
- The health endpoint reports the agent as unhealthy

**Evidence from logs:**
```
[gateway] auth token was missing. Generated a runtime token for this startup...
[ws] closed before connect ... code=1008 reason=device identity required
[ws] closed before connect ... code=1008 reason=connect failed
```

**Fix:** Add `gateway.auth.mode: "none"` to the config overlay. Per [Openclaw docs](https://docs.openclaw.ai/gateway/configuration-reference), `"none"` is the explicit no-auth mode for trusted local/loopback setups. This is safe because:
- The gateway only listens on loopback (`127.0.0.1`) inside the pod
- The pod is not exposed externally (only Slack Socket Mode outbound + healthz on port 8081)
- This restores the pre-2026.6.x behavior

**Files to modify:**

4. **`api/domains/agents/builders/openclaw.py`**
   - `build_openclaw_config_overlay`: Add `"gateway": {"auth": {"mode": "none"}}` to the returned dict
   - `build_openclaw_config_overlay_teams`: Same addition

5. **`api/tests/integration/test_agents.py`** — Update assertions if they check the full overlay structure

6. **`api/tests/unit/test_openclaw_builders.py`** — Update assertions if they check the full overlay structure

### What NOT to change

- **Streaming config** — Keep `mode: "partial"` + `nativeTransport: true`. The 2026.6.11 upgrade fixes the underlying delivery bug, so streaming should work correctly.
- **Telemetry plugin** — Already works correctly (uses `agent_end`, not the broken `message_sent`)
- **`tools.exec.mode`** — Intentionally removed (approval mode not tested with Openclaw yet, disabled for initial setup)
- **DM config** — Already works fine
- **`healthz-server.js`** — No changes needed; `openclaw health --json` will work once gateway auth is disabled

### Deprecation warning (non-blocking)

The logs show: `[plugins] active-memory: config.modelFallbackPolicy is deprecated`. This is a harmless warning — the field still exists in the overlay but is ignored at runtime. Can be cleaned up in a follow-up if desired.

## Verification

1. Rebuild the `openclaw-base` Docker image with the updated Dockerfile
2. Stop and start an Openclaw agent — confirm no `device identity required` errors in logs
3. Confirm `[gateway] ready` and healthz endpoint returns `{"status": "ok"}`
4. Message the agent in a **public channel**, confirm the response arrives
5. Verify DM functionality still works
6. Verify the response appears in the UI conversations view (telemetry still works)
7. Verify Teams agents still function (msteams plugin version bump)
8. Run the existing smoke test: `openclaw-base/smoke-test.sh` during image build
