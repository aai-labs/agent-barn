const http = require('http');
const https = require('https');
const { execFile } = require('child_process');

const PORT = 8081;
const PROXY_PORT = 8090;
const CACHE_TTL_MS = 10_000;
const TOKEN_POLL_MS = 5 * 60 * 1000; // 5 minutes

const AGENT_PLATFORM = process.env.AGENT_PLATFORM || 'slack';
const SKIP_VALIDATION = ['1', 'true', 'yes'].includes(
  (process.env.SKIP_SLACK_TOKEN_VALIDATION || '').toLowerCase()
);
const LITELLM_PROXY_TARGET = process.env.LITELLM_PROXY_TARGET || '';

let cache = null;
let tokenCache = null;
let proxyServer = null;
let refreshing = false;

const TERMINAL_LLM_ERRORS = {
  401: 'LLM API key is invalid or expired. Check your API key configuration.',
  402: 'OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits.',
  403: 'LLM API access denied. Check your account permissions.',
};

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

const server = http.createServer((req, res) => {
  if (req.method !== 'GET') { res.writeHead(404); res.end(); return; }

  if (req.url === '/ready') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ready: true }));
    return;
  }

  if (req.url === '/healthz') {
    // Token failure surfaces immediately as an error
    if (tokenCache && !tokenCache.ok) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'error', reason: tokenCache.reason }));
      return;
    }

    if (!cache || !tokenCache) {
      res.writeHead(503, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'starting' }));
      return;
    }
    if (cache.ok) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
      return;
    }
    if (cache.everConnected) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'error', reason: cache.reason }));
      return;
    }
    res.writeHead(503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'starting', reason: cache.reason }));
    return;
  }

  res.writeHead(404);
  res.end();
});

process.on('SIGTERM', () => {
  if (proxyServer) proxyServer.close();
  server.close(() => process.exit(0));
});

server.listen(PORT, () => console.log('[healthz] listening on :' + PORT));

// ---------------------------------------------------------------------------
// LLM proxy — intercepts terminal errors and returns clean messages
// ---------------------------------------------------------------------------

if (LITELLM_PROXY_TARGET) {
  const targetUrl = new URL(LITELLM_PROXY_TARGET);
  const targetModule = targetUrl.protocol === 'https:' ? https : http;
  const targetPort = targetUrl.port || (targetUrl.protocol === 'https:' ? 443 : 80);

  proxyServer = http.createServer((clientReq, clientRes) => {
    const opts = {
      hostname: targetUrl.hostname,
      port: targetPort,
      path: clientReq.url,
      method: clientReq.method,
      headers: { ...clientReq.headers, host: targetUrl.host },
      timeout: 120_000,
    };

    const upstreamReq = targetModule.request(opts, (upstreamRes) => {
      const cleanMsg = TERMINAL_LLM_ERRORS[upstreamRes.statusCode];
      if (cleanMsg) {
        // Consume upstream body then send clean response
        const chunks = [];
        upstreamRes.on('data', (c) => chunks.push(c));
        upstreamRes.on('end', () => {
          const body = JSON.stringify({
            error: { message: cleanMsg, type: null, param: null, code: String(upstreamRes.statusCode) }
          });
          clientRes.writeHead(upstreamRes.statusCode, {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(body),
          });
          clientRes.end(body);
        });
      } else {
        clientRes.writeHead(upstreamRes.statusCode, upstreamRes.headers);
        upstreamRes.pipe(clientRes);
      }
    });

    upstreamReq.on('error', () => {
      const body = JSON.stringify({
        error: { message: 'LLM proxy upstream unreachable', type: null, param: null, code: '502' }
      });
      clientRes.writeHead(502, {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      });
      clientRes.end(body);
    });

    clientReq.pipe(upstreamReq);
  });

  proxyServer.listen(PROXY_PORT, () => console.log('[llm-proxy] listening on :' + PROXY_PORT));
}
