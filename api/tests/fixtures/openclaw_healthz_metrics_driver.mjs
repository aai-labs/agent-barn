// Runs inside openclaw-base: the real healthz server must report this container's own
// cgroup limits, read as the image's own user.
//
// The caller starts the container with `--memory 1g --cpus 0.5`, so the limits are
// known. A fake cgroup directory proves the arithmetic; only the image can prove that
// the files exist at /sys/fs/cgroup and that the user the runtime runs as may read them.
//
// Usage: node openclaw_healthz_metrics_driver.mjs /path/to/healthz-server.js
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import http from 'node:http';

const PORT = '18081';
const GIB = 1024 ** 3;

function get(path) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: '127.0.0.1', port: PORT, path, timeout: 5000 }, (res) => {
        let body = '';
        res.on('data', (chunk) => (body += chunk));
        res.on('end', () => resolve({ status: res.statusCode, body }));
      })
      .on('error', reject);
  });
}

function samples(text) {
  const values = {};
  for (const line of text.split('\n')) {
    if (line && !line.startsWith('#')) {
      const [name, value] = line.split(' ');
      values[name] = Number(value);
    }
  }
  return values;
}

const server = spawn(process.execPath, [process.argv[2]], {
  env: { ...process.env, HEALTHZ_PORT: PORT },
  stdio: 'ignore',
});

try {
  const deadline = Date.now() + 15_000;
  for (;;) {
    try {
      if ((await get('/ready')).status === 200) break;
    } catch {
      // not listening yet
    }
    if (Date.now() > deadline) throw new Error('healthz server did not start');
    await new Promise((resolve) => setTimeout(resolve, 200));
  }

  const found = samples((await get('/metrics')).body);
  const uid = process.getuid();

  assert.equal(found.agent_cgroup_metrics_available, 1, `cgroup v2 files unreadable as uid ${uid}: ${JSON.stringify(found)}`);
  assert.equal(found.agent_memory_limit_bytes, GIB, JSON.stringify(found));
  assert.equal(found.agent_cpu_limit_cores, 0.5, JSON.stringify(found));
  assert.ok(found.agent_memory_working_set_bytes > 0, JSON.stringify(found));
  assert.ok(found.agent_cpu_usage_seconds_total > 0, JSON.stringify(found));
  assert.ok('agent_cpu_periods_total' in found && 'agent_cpu_throttled_periods_total' in found, JSON.stringify(found));
  console.log(`OK: cgroup metrics readable as uid ${uid}`);
} finally {
  server.kill();
}
