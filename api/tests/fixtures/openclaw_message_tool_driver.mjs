// Exercise the real native tool factory, policy filter, and send path without provider I/O.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createOpenClawTools} from '/usr/local/lib/node_modules/openclaw/dist/openclaw-tools-CiSSm2Og.js';
import {isToolAllowedByPolicyName, filterToolsByPolicy} from '/usr/local/lib/node_modules/openclaw/dist/tool-policy-match-BKTxaTvX.js';
import {r as enforceCrossContextPolicy} from '/usr/local/lib/node_modules/openclaw/dist/outbound-policy-D8vGsf4T.js';

const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.env.TELEGRAM_BOT_TOKEN = '123:fixture';

function nativeMessageTool(cfg) {
  const tools = createOpenClawTools({
    config: cfg,
    workspaceDir: cfg.agents.defaults.workspace,
    agentChannel: 'telegram',
    currentChannelId: '-1009',
  });
  assert(tools.some(tool => tool.name === 'message'), 'native message tool must be constructed');
  const message = filterToolsByPolicy(tools, cfg.tools).find(tool => tool.name === 'message');
  assert(message, 'native message tool must be available to the agent');
  return message;
}

const message = nativeMessageTool(config);
assert(isToolAllowedByPolicyName('cron', config.tools), 'native schedules must remain available');
for (const [target, replyTo] of [['-1009', '77'], ['-1010', undefined]]) {
  const result = await message.execute('native-message-regression', {
    action: 'send', channel: 'telegram', target, replyTo,
    message: 'Daily update', dryRun: true,
  });
  assert.equal(result.details.channel, 'telegram');
  assert.equal(result.details.to, `telegram:${target}`);
  assert.equal(result.details.dryRun, true);
}

// Native restrictions still apply when the tool is exposed.
const restricted = structuredClone(config);
restricted.tools.message = {
  actions: {allow: ['send']},
  crossContext: {allowWithinProvider: false, allowAcrossProviders: false},
};
await assert.rejects(nativeMessageTool(restricted).execute('restricted-message-regression', {
  action: 'send', channel: 'telegram', target: '-1010',
  message: 'Blocked update', dryRun: true,
}), /Cross-context messaging denied/);
await assert.rejects(nativeMessageTool(restricted).execute('restricted-action-regression', {
  action: 'delete', channel: 'telegram', target: '-1009', messageId: '77', dryRun: true,
}), /Message action "delete" is disabled/);
assert.throws(() => enforceCrossContextPolicy({
  cfg: config,
  channel: 'discord', action: 'send', args: {to: 'channel:other'},
  toolContext: {currentChannelProvider: 'telegram', currentChannelId: '-1009'},
}), /Cross-context messaging denied/);
console.log('OpenClaw native message availability, threaded/cross-channel sends, and context guards passed');
