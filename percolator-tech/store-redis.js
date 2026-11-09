import { createClient } from 'redis';

const KEY = 'perc:installs';
const SEQ = 'perc:installs:seq';

export async function createRedisStore(redisUrl) {
  const client = createClient({ url: redisUrl });
  client.on('error', (e) => console.error('redis error', e?.message || e));
  await client.connect();

  return {
    async add({ source, agentId, version, cluster, ipHash }) {
      const id = await client.incr(SEQ);
      const createdAt = new Date().toISOString();
      const row = {
        id,
        source,
        agentId: agentId || null,
        version: version || null,
        cluster: cluster || null,
        ipHash,
        createdAt,
      };
      await client.lPush(KEY, JSON.stringify(row));
      // keep last 50k events
      await client.lTrim(KEY, 0, 49999);
      return { id, createdAt };
    },
    async rateLimitCount(ipHash, windowMs) {
      const cutoff = Date.now() - windowMs;
      const raw = await client.lRange(KEY, 0, 500);
      let n = 0;
      for (const s of raw) {
        try {
          const r = JSON.parse(s);
          if (r.ipHash === ipHash && Date.parse(r.createdAt) > cutoff) n++;
        } catch { /* skip */ }
      }
      return n;
    },
    async stats({ includeTest = false } = {}) {
      const raw = await client.lRange(KEY, 0, -1);
      const now = Date.now();
      const bySource = {};
      const byDay = {};
      let total = 0;
      let last24h = 0;
      for (const s of raw) {
        let r;
        try { r = JSON.parse(s); } catch { continue; }
        if (!includeTest && r.source === 'test') continue;
        total++;
        bySource[r.source] = (bySource[r.source] || 0) + 1;
        const d = String(r.createdAt).slice(0, 10);
        byDay[d] = (byDay[d] || 0) + 1;
        if (now - Date.parse(r.createdAt) < 864e5) last24h++;
      }
      return { total, last24h, bySource, byDay };
    },
  };
}
