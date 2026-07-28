const http = require('http');
const https = require('https');
const { execFile } = require('child_process');

const PORT = parseInt(process.env.HEALTHZ_PORT || '8081', 10);
const CACHE_TTL_MS = 10_000;
const TOKEN_POLL_MS = 5 * 60 * 1000; // 5 minutes

const AGENT_PLATFORM = process.env.AGENT_PLATFORM || 'slack';
const SKIP_VALIDATION = ['1', 'true', 'yes'].includes(
  (process.env.SKIP_SLACK_TOKEN_VALIDATION || '').toLowerCase()
);

let cache = null;
let tokenCache = null;
let refreshing = false;

function slackPost(path, token) {
  return new Promise((resolve) => {
    const req = https.request(
      { hostname: 'slack.com', path: `/api/${path}`, method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json', 'Content-Length': 0 } },
      (res) => {
        let raw = '';
        res.on('data', (c) => raw += c);
        res.on('end', () => {
          try { resolve(JSON.parse(raw)); } catch { resolve({ ok: false, error: 'parse_error' }); }
        });
      }
    );
    req.on('error', (e) => resolve({ ok: false, error: e.message }));
    req.setTimeout(15_000, () => { req.destroy(); resolve({ ok: false, error: 'timeout' }); });
    req.end();
  });
}

function telegramGetMe(token) {
  return new Promise((resolve) => {
    const req = https.request(
      { hostname: 'api.telegram.org', path: `/bot${token}/getMe`, method: 'GET' },
      (res) => {
        let raw = '';
        res.on('data', (c) => raw += c);
        res.on('end', () => {
          try { resolve(JSON.parse(raw)); } catch { resolve({ ok: false, description: 'parse_error' }); }
        });
      }
    );
    req.on('error', (e) => resolve({ ok: false, description: e.message }));
    req.setTimeout(15_000, () => { req.destroy(); resolve({ ok: false, description: 'timeout' }); });
    req.end();
  });
}

async function validateTokens() {
  if (SKIP_VALIDATION) {
    tokenCache = { ok: true };
    return;
  }

  if (AGENT_PLATFORM === 'telegram') {
    const telegramToken = process.env.TELEGRAM_BOT_TOKEN || '';
    const result = await telegramGetMe(telegramToken);
    if (!result.ok) {
      tokenCache = { ok: false, reason: `Invalid Telegram bot token: ${result.description || 'unknown_error'}` };
      return;
    }
    tokenCache = { ok: true };
    return;
  }

  const botToken = process.env.SLACK_BOT_TOKEN || '';
  const appToken = process.env.SLACK_APP_TOKEN || '';

  const botResult = await slackPost('auth.test', botToken);
  if (!botResult.ok) {
    tokenCache = { ok: false, reason: `Invalid bot token: ${botResult.error || 'unknown_error'}` };
    return;
  }

  const appResult = await slackPost('apps.connections.open', appToken);
  if (!appResult.ok) {
    tokenCache = { ok: false, reason: `Invalid app token: ${appResult.error || 'unknown_error'}` };
    return;
  }

  tokenCache = { ok: true };
}

function refresh() {
  if (refreshing) return;
  refreshing = true;
  execFile('openclaw', ['health', '--json'], { timeout: 15_000 }, (err, stdout) => {
    refreshing = false;
    if (err) {
      cache = { ok: false, everConnected: false, reason: err.message };
      return;
    }
    try {
      const d = JSON.parse(stdout);
      const order = d.channelOrder || [];
      if (!order.length) { cache = { ok: false, everConnected: false, reason: 'no channels configured' }; return; }
      for (const ch of order) {
        const channel = d.channels[ch];
        if (channel?.healthState !== 'healthy') {
          if (AGENT_PLATFORM === 'telegram' && !channel?.lastError) {
            continue;
          }
          const everConnected = typeof channel?.lastConnectedAt === 'number';
          cache = { ok: false, everConnected, reason: channel?.lastError || 'channel ' + ch + ' not connected' };
          return;
        }
      }
      cache = { ok: true };
    } catch {
      cache = { ok: false, everConnected: false, reason: 'failed to parse health output' };
    }
  });
}

validateTokens();
setInterval(validateTokens, TOKEN_POLL_MS);

refresh();
setInterval(refresh, CACHE_TTL_MS);

function metricsText() {
  const ok = cache?.ok ? 1 : 0;
  const ever = (cache?.ok || cache?.everConnected) ? 1 : 0;
  // Token gauge stays 1 while unknown/starting; 0 only on a definite
  // failure, so a slow first validation never trips an alert.
  const tokensOk = (tokenCache && !tokenCache.ok) ? 0 : 1;
  const lines = [
    '# HELP agent_healthz_ok 1 if the agent runtime is reachable, 0 otherwise',
    '# TYPE agent_healthz_ok gauge',
    `agent_healthz_ok ${ok}`,
    '# HELP agent_healthz_ever_connected 1 once the runtime has connected at least once',
    '# TYPE agent_healthz_ever_connected gauge',
    `agent_healthz_ever_connected ${ever}`,
    '# HELP agent_slack_tokens_ok 0 if Slack token validation definitely failed, 1 otherwise',
    '# TYPE agent_slack_tokens_ok gauge',
    `agent_slack_tokens_ok ${tokensOk}`,
  ];
  return lines.join('\n') + '\n';
}

function healthzResult() {
  // Token failure surfaces immediately as an error
  if (tokenCache && !tokenCache.ok) return [500, { status: 'error', reason: tokenCache.reason }];
  if (!cache || !tokenCache) return [503, { status: 'starting' }];
  if (cache.ok) return [200, { status: 'ok' }];
  if (cache.everConnected) return [500, { status: 'error', reason: cache.reason }];
  return [503, { status: 'starting', reason: cache.reason }];
}

function sendJson(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  if (req.method !== 'GET') { res.writeHead(404); res.end(); return; }

  if (req.url === '/ready') {
    sendJson(res, 200, { ready: true });
  } else if (req.url === '/metrics') {
    // Prometheus exposition content type; canonical value lives in
    // api/core/metrics.py (standalone script, cannot share the constant).
    res.writeHead(200, { 'Content-Type': 'text/plain; version=0.0.4; charset=utf-8' });
    res.end(metricsText());
  } else if (req.url === '/healthz') {
    const [code, body] = healthzResult();
    sendJson(res, code, body);
  } else {
    res.writeHead(404);
    res.end();
  }
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));

server.listen(PORT, () => console.log('[healthz] listening on :' + PORT));
