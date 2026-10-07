// Exercise the pinned native scheduler with model/provider execution replaced at its boundary.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { t as CronService } from '/usr/local/lib/node_modules/openclaw/dist/service-BpqbhOtN.js';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'native-cron-'));
process.env.OPENCLAW_STATE_DIR = root;
const executed = [];
const service = new CronService({
  storePath: path.join(root, 'cron/jobs.json'),
  cronEnabled: true,
  log: { info() {}, warn() {}, error() {}, debug() {} },
  listConfiguredChannels: () => ['slack'],
  defaultAgentId: 'main',
  enqueueSystemEvent() {},
  requestHeartbeatNow() {},
  runIsolatedAgentJob: async ({job}) => {
    executed.push(job);
    return {status: 'ok', summary: 'Native result', delivered: true};
  },
});
try {
  await service.start();
  const job = await service.add({
    name: 'native-webhook',
    agentId: 'main',
    schedule: {kind: 'at', at: new Date(Date.now() + 2000).toISOString()},
    sessionTarget: 'isolated',
    wakeMode: 'now',
    payload: {kind: 'agentTurn', message: 'Native result'},
    delivery: {mode: 'announce', channel: 'slack', to: 'C_HOME'},
    deleteAfterRun: true,
    enabled: true,
  });
  const deadline = Date.now() + 30000;
  while (!executed.length && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
  await new Promise(resolve => setTimeout(resolve, 500));
  assert.equal(executed.length, 1);
  assert.deepEqual(executed[0].delivery, {mode: 'announce', channel: 'slack', to: 'C_HOME'});
  assert.equal((await service.list({includeDisabled: true})).some(item => item.id === job.id), false);
  assert.equal(fs.existsSync(path.join(root, 'agentbarn-messages.sqlite3')), false);
  console.log('OpenClaw native one-shot execution once, explicit destination, and no bridge passed');
} finally {
  service.stop();
}
