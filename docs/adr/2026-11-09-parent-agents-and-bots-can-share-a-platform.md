# A Parent Agent and its Bots can share a messaging platform

Status: Accepted
Date: 2026-11-09
Origin: AF-425

This supersedes the platform rule in [Bots share their Parent Agent's gateway](2026-11-05-bots-share-their-parent-agents-gateway.md). Hermes `v2026.8.19` gives every profile's scheduled jobs the default profile's connections, so a Bot's job could go out through its Parent Agent's connection. Upstream fixed this from `0.21.6` by delivering through the job profile's own connections. The maintainer chose to backport that behaviour as a build-time patch, `hermes-base/patch-bot-cron-delivery.py`, and allow the overlap. A Hermes upgrade would have changed every Hermes Agent and needed all Bot verification repeated.

Agent Barn Telegram on a Parent Agent stays refused alongside a Bot's own Telegram, because it sets `TELEGRAM_WEBHOOK_URL` for the whole process.

## Revisit when

- Hermes is upgraded to a version with the upstream fix. The patch fails the image build if the source changes; review it then and remove it if it is no longer needed.
