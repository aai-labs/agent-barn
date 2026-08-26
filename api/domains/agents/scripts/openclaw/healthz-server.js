const http = require('http');
const { execFile } = require('child_process');


const PROXY_PORT = 8090;
const PORT = parseInt(process.env.HEALTHZ_PORT || '8081', 10);
const CACHE_TTL_MS = 10_000;
const LITELLM_PROXY_TARGET = process.env.LITELLM_PROXY_TARGET || '';

let cache = null;
let proxyServer = null;
let refreshing = false;

const TERMINAL_LLM_ERRORS = {
  401: 'LLM API key is invalid or expired. Check your API key configuration.',
  402: 'OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits.',
  403: 'LLM API access denied. Check your account permissions.',
};

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
      JSON.parse(stdout);
      cache = { ok: true, everConnected: true };
    } catch {
      cache = { ok: false, everConnected: false, reason: 'failed to parse health output' };
    }
  });
}

refresh();
setInterval(refresh, CACHE_TTL_MS);

function metricsText() {
  const ok = cache?.ok ? 1 : 0;
  const ever = (cache?.ok || cache?.everConnected) ? 1 : 0;
  const lines = [
    '# HELP agent_healthz_ok 1 if the agent runtime is reachable, 0 otherwise',
    '# TYPE agent_healthz_ok gauge',
    `agent_healthz_ok ${ok}`,
    '# HELP agent_healthz_ever_connected 1 once the runtime has connected at least once',
    '# TYPE agent_healthz_ever_connected gauge',
    `agent_healthz_ever_connected ${ever}`,
  ];
  return lines.join('\n') + '\n';
}

function healthzResult() {
  if (!cache) return [503, { status: 'starting' }];
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
      if (!clientRes.headersSent && !clientRes.destroyed) {
        const body = JSON.stringify({
          error: { message: 'LLM proxy upstream unreachable', type: null, param: null, code: '502' }
        });
        clientRes.writeHead(502, {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        });
        clientRes.end(body);
      } else {
        clientRes.destroy();
      }
    });

    clientReq.pipe(upstreamReq);
    clientReq.on('close', () => { if (!clientReq.complete) upstreamReq.destroy(); });
  });

  proxyServer.listen(PROXY_PORT, () => console.log('[llm-proxy] listening on :' + PROXY_PORT));
}
