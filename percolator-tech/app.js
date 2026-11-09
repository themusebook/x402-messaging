import http from 'node:http';
import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCES = new Set(['skill', 'repo', 'template', 'agent', 'test']);
const RATE_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const RATE_MAX = 30;

export function createMemoryStore() {
  const rows = [];
  return {
    async add({ source, agentId, version, cluster, ipHash }) {
      const row = {
        id: rows.length + 1,
        source,
        agentId: agentId || null,
        version: version || null,
        cluster: cluster || null,
        ipHash,
        createdAt: new Date(),
      };
      rows.push(row);
      return { id: row.id, createdAt: row.createdAt };
    },
    async rateLimitCount(ipHash, windowMs) {
      const cutoff = Date.now() - windowMs;
      return rows.filter((r) => r.ipHash === ipHash && r.createdAt.getTime() > cutoff).length;
    },
    async stats({ includeTest = false } = {}) {
      const list = includeTest ? rows : rows.filter((r) => r.source !== 'test');
      const now = Date.now();
      const bySource = {};
      const byDay = {};
      let last24h = 0;
      for (const r of list) {
        bySource[r.source] = (bySource[r.source] || 0) + 1;
        const d = r.createdAt.toISOString().slice(0, 10);
        byDay[d] = (byDay[d] || 0) + 1;
        if (now - r.createdAt.getTime() < 864e5) last24h++;
      }
      return { total: list.length, last24h, bySource, byDay };
    },
  };
}

function sendJson(res, code, obj) {
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'cache-control': 'no-store',
  });
  res.end(JSON.stringify(obj));
}

function sendHtml(res, code, html) {
  res.writeHead(code, {
    'content-type': 'text/html; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(html);
}

function sendText(res, code, text, type = 'text/plain; charset=utf-8') {
  res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store' });
  res.end(text);
}

function readJson(req, limit = 4096) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(new Error('too large'));
        req.destroy();
      } else chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        reject(new Error('invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

function clientIp(req) {
  const xf = req.headers['x-forwarded-for'];
  if (typeof xf === 'string' && xf.length) return xf.split(',')[0].trim();
  return req.socket?.remoteAddress || '0.0.0.0';
}

function hashIp(ip, salt) {
  return createHmac('sha256', salt).update(String(ip)).digest('hex');
}

function validateInstall(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return 'body must be a JSON object';
  if (typeof body.source !== 'string' || !SOURCES.has(body.source)) {
    return 'source must be one of skill|repo|template|agent|test';
  }
  for (const k of ['agent_id', 'version', 'cluster']) {
    if (body[k] !== undefined && typeof body[k] !== 'string') return `${k} must be a string`;
    if (typeof body[k] === 'string' && body[k].length > 128) return `${k} too long`;
  }
  return null;
}

function loadPage(name) {
  return readFileSync(join(__dirname, 'public', name), 'utf8');
}

async function fetchMarkets(marketsUrl) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch(marketsUrl, { signal: ctrl.signal, headers: { accept: 'application/json' } });
    if (!r.ok) throw new Error(`markets ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

function installPingScript(source, base) {
  const src = SOURCES.has(source) ? source : 'repo';
  return `#!/usr/bin/env bash
# Percolator install ping — fires once, never blocks the install.
set -euo pipefail
BASE="${base}"
SRC="${src}"
AGENT_ID="\${PERCOLATOR_AGENT_ID:-}"
VERSION="\${PERCOLATOR_VERSION:-}"
CLUSTER="\${PERCOLATOR_CLUSTER:-}"
payload=$(printf '{"source":"%s"' "$SRC")
[ -n "$AGENT_ID" ] && payload+=$(printf ',"agent_id":"%s"' "$AGENT_ID")
[ -n "$VERSION" ] && payload+=$(printf ',"version":"%s"' "$VERSION")
[ -n "$CLUSTER" ] && payload+=$(printf ',"cluster":"%s"' "$CLUSTER")
payload+='}'
curl -fsS -m 5 -X POST "$BASE/api/install" \\
  -H 'content-type: application/json' \\
  -d "$payload" >/dev/null 2>&1 || true
`;
}

export function createServer(store, { ipSalt, marketsUrl } = {}) {
  const homeHtml = loadPage('index.html');
  const installsHtml = loadPage('installs.html');

  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url || '/', 'http://x');
      const path = url.pathname;

      if (req.method === 'OPTIONS') {
        res.writeHead(204, {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET,POST,OPTIONS',
          'access-control-allow-headers': 'content-type',
        });
        return res.end();
      }

      if (req.method === 'GET' && (path === '/api/health' || path === '/healthz')) {
        return sendJson(res, 200, { ok: true, service: 'percolator-tech' });
      }

      if (req.method === 'GET' && path === '/api/installs/stats') {
        const stats = await store.stats({ includeTest: false });
        return sendJson(res, 200, { ok: true, ...stats });
      }

      if (req.method === 'GET' && path === '/api/markets') {
        try {
          const data = await fetchMarkets(marketsUrl);
          return sendJson(res, 200, data);
        } catch (e) {
          return sendJson(res, 502, { error: 'markets upstream unavailable', detail: String(e.message || e) });
        }
      }

      if (req.method === 'POST' && path === '/api/install') {
        let body;
        try {
          body = await readJson(req);
        } catch (e) {
          return sendJson(res, 400, { error: e.message });
        }
        const err = validateInstall(body);
        if (err) return sendJson(res, 400, { error: err });

        const ip = clientIp(req);
        const ipHash = hashIp(ip, ipSalt);
        const recent = await store.rateLimitCount(ipHash, RATE_WINDOW_MS);
        if (recent >= RATE_MAX) return sendJson(res, 429, { error: 'rate limited' });

        const saved = await store.add({
          source: body.source,
          agentId: body.agent_id,
          version: body.version,
          cluster: body.cluster,
          ipHash,
        });
        return sendJson(res, 201, { ok: true, id: saved.id });
      }

      // one-liner ping scripts for installers
      const ping = path.match(/^\/i\/([a-z]+)\.sh$/);
      if (req.method === 'GET' && ping) {
        const host = req.headers['x-forwarded-host'] || req.headers.host || 'percolator.tech';
        const proto = req.headers['x-forwarded-proto'] || 'https';
        const base = `${proto}://${host}`;
        return sendText(res, 200, installPingScript(ping[1], base), 'text/x-shellscript; charset=utf-8');
      }

      if (req.method === 'GET' && path === '/') {
        return sendHtml(res, 200, homeHtml);
      }
      if (req.method === 'GET' && path === '/installs') {
        return sendHtml(res, 200, installsHtml);
      }

      sendJson(res, 404, { error: 'not found' });
    } catch (e) {
      console.error('handler error', e?.message || e);
      sendJson(res, 500, { error: 'internal error' });
    }
  });
}

// silence unused import warning for createHash if tree-shaken elsewhere
void createHash;
void timingSafeEqual;
