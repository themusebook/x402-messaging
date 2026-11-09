import pg from 'pg';

export async function createPgStore(connectionString) {
  const pool = new pg.Pool({
    connectionString,
    max: 3,
    ssl: /render\.com|amazonaws\.com/.test(connectionString)
      ? { rejectUnauthorized: false }
      : undefined,
  });

  await pool.query(`
    CREATE TABLE IF NOT EXISTS perc_installs (
      id bigserial PRIMARY KEY,
      source text NOT NULL,
      agent_id text,
      version text,
      cluster text,
      ip_hash text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await pool.query(`CREATE INDEX IF NOT EXISTS perc_installs_source_idx ON perc_installs (source)`);
  await pool.query(`CREATE INDEX IF NOT EXISTS perc_installs_created_idx ON perc_installs (created_at)`);
  await pool.query(`CREATE INDEX IF NOT EXISTS perc_installs_ip_day_idx ON perc_installs (ip_hash, (created_at::date))`);

  return {
    async add({ source, agentId, version, cluster, ipHash }) {
      const r = await pool.query(
        `INSERT INTO perc_installs(source, agent_id, version, cluster, ip_hash)
         VALUES ($1,$2,$3,$4,$5) RETURNING id, created_at`,
        [source, agentId || null, version || null, cluster || null, ipHash]
      );
      return { id: r.rows[0].id, createdAt: r.rows[0].created_at };
    },
    async rateLimitCount(ipHash, windowMs) {
      const r = await pool.query(
        `SELECT count(*)::int AS n FROM perc_installs
         WHERE ip_hash = $1 AND created_at > now() - ($2::bigint * interval '1 millisecond')`,
        [ipHash, windowMs]
      );
      return r.rows[0].n;
    },
    async stats({ includeTest = false } = {}) {
      const where = includeTest ? '' : `WHERE source <> 'test'`;
      const t = await pool.query(
        `SELECT count(*)::int AS total,
                count(*) FILTER (WHERE created_at > now() - interval '24 hours')::int AS last24h
         FROM perc_installs ${where}`
      );
      const bySource = await pool.query(
        `SELECT source, count(*)::int AS n FROM perc_installs ${where} GROUP BY 1 ORDER BY 2 DESC`
      );
      const byDay = await pool.query(
        `SELECT to_char(created_at AT TIME ZONE 'UTC','YYYY-MM-DD') AS d, count(*)::int AS n
         FROM perc_installs ${where} GROUP BY 1 ORDER BY 1`
      );
      return {
        total: t.rows[0].total,
        last24h: t.rows[0].last24h,
        bySource: Object.fromEntries(bySource.rows.map((r) => [r.source, r.n])),
        byDay: Object.fromEntries(byDay.rows.map((r) => [r.d, r.n])),
      };
    },
  };
}
