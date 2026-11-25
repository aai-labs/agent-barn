// Puts WhatsApp messages through OpenClaw's core access decisions for each rendered
// `channels.whatsapp` config. Run by openclaw_whatsapp_access_driver.py inside the image.
//
// @openclaw/whatsapp is installed from npm at start, so it is not in the image. Its
// inbound-policy glue (resolveWhatsAppInboundPolicy and the access checks around it in
// @openclaw/whatsapp 2026.8.2) is mirrored here; the decisions it delegates to come from
// the pinned core: sender access, the group allowlist and the mention rule.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { resolveStableChannelMessageIngress } from '/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/channel-ingress-runtime.js';
import {
  resolveChannelGroupPolicy,
  resolveChannelGroupRequireMention,
} from '/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/channel-policy.js';

process.env.OPENCLAW_STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'whatsapp-access-'));
const { self, messages, cases } = JSON.parse(process.env.WHATSAPP_CASES);
const selfE164 = `+${self}`;
const e164 = (value) => {
  const digits = String(value).replace(/[^0-9]/g, '');
  return digits ? `+${digits}` : null;
};

async function senderAllowed(channel, policy, { sender, chatId, isGroup }) {
  const access = await resolveStableChannelMessageIngress({
    channelId: 'whatsapp',
    accountId: 'default',
    identity: { key: 'whatsapp-sender-phone', kind: 'phone', normalize: e164, sensitivity: 'pii', entryIdPrefix: 'whatsapp-entry' },
    cfg: { channels: { whatsapp: channel } },
    useDefaultPairingStore: true,
    subject: { stableId: sender },
    conversation: { kind: isGroup ? 'group' : 'direct', id: chatId },
    dmPolicy: policy.dmPolicy,
    groupPolicy: policy.groupPolicy,
    policy: { groupAllowFromFallbackToAllowFrom: false },
    providerMissingFallbackApplied: false,
    allowFrom:
      !isGroup && channel.selfChatMode !== false && sender === selfE164
        ? [...policy.dmAllowFrom, sender]
        : policy.dmAllowFrom,
    groupAllowFrom: policy.groupAllowFrom,
  });
  return access.senderAccess.decision === 'allow';
}

async function admits(channel, message) {
  const configuredAllowFrom = channel.allowFrom ?? [];
  const policy = {
    dmPolicy: channel.dmPolicy ?? 'pairing',
    groupPolicy: channel.groupPolicy,
    dmAllowFrom: configuredAllowFrom.length > 0 ? configuredAllowFrom : [selfE164],
    groupAllowFrom: channel.groupAllowFrom?.length ? channel.groupAllowFrom : configuredAllowFrom,
  };
  const sender = `+${message.sender}`;
  const isGroup = message.chat.endsWith('@g.us');
  if (!isGroup) {
    const chatId = e164(message.chat.split('@')[0]);
    // The owner's own DMs count only in their Message yourself chat, in self-chat mode.
    if (sender === selfE164 && (channel.selfChatMode === false || chatId !== selfE164)) return false;
    return senderAllowed(channel, policy, { sender, chatId, isGroup });
  }
  const groupCfg = { channels: { whatsapp: { groupPolicy: policy.groupPolicy, groups: channel.groups } } };
  const groupPolicy = resolveChannelGroupPolicy({
    cfg: groupCfg,
    channel: 'whatsapp',
    groupId: message.chat,
    hasGroupAllowFrom: policy.groupAllowFrom.length > 0,
  });
  if (policy.groupPolicy === 'disabled' || (groupPolicy.allowlistEnabled && !groupPolicy.allowed)) return false;
  if (!(await senderAllowed(channel, policy, { sender, chatId: message.chat, isGroup }))) return false;
  const requireMention = resolveChannelGroupRequireMention({ cfg: groupCfg, channel: 'whatsapp', groupId: message.chat });
  return !requireMention || message.mentions;
}

let broken = false;
for (const { channel, admitted } of cases) {
  const got = [];
  for (const message of messages) if (await admits(channel, message)) got.push(message.label);
  if (JSON.stringify(got.sort()) !== JSON.stringify([...admitted].sort())) {
    broken = true;
    console.error(`whatsapp access contract broken for ${JSON.stringify(channel)}: admitted ${JSON.stringify(got)}, expected ${JSON.stringify(admitted)}`);
  }
}
if (broken) process.exit(1);
