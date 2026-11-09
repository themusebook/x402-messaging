# percolator.tech

Home page + install tracker for **$CLAWD Percolator**.

- `GET /` — home (story, devnet proof, program IDs, mainnet Route A, live markets, install counter)
- `GET /installs` — public stats page
- `GET /api/health` — health check
- `GET /api/installs/stats` — totals by source and by day (`source=test` excluded)
- `POST /api/install` — `{ "source": "skill"|"repo"|"template"|"agent"|"test", "agent_id?", "version?", "cluster?" }`
- `GET /i/<source>.sh` — one-liner ping script for installers
- `GET /api/markets` — proxy to clawd markets API

Educational / unaudited. No promised returns. Brand is **$CLAWD** only.

## Deploy

Render free web service `percolator-tech` + free Key Value `percolator-tech-kv`.

Env vars (set in Render only — never commit):

- `REDIS_URL` — from `percolator-tech-kv` connection string (Blueprint `fromService`)
- `DATABASE_URL` — optional; used if `REDIS_URL` is unset (Postgres path with `perc_` tables only)
- `IP_HASH_SALT` — long random secret for HMAC of client IPs (`generateValue` in Blueprint)
- `MARKETS_URL` — default `https://percolator.clawdchain.trade/api/markets`
- `PORT` — set by Render

Note: this workspace already has one free Postgres (`musebot-install-counter-db`, expires **2026-11-24 America/New_York**). Render allows only one free DB, so installs persist in free Key Value instead. KV free tier is ephemeral (persistenceMode off) — renew/migrate before relying on long history.

## Wire the install ping (do not skip)

### clawd-percolator skill

Add near the end of the skill's quick-start / install instructions (or a post-install hook in `scripts/`):

```bash
# Fire-and-forget install ping (never fails the install)
curl -fsS -m 5 https://percolator.tech/i/skill.sh | bash || true
# Or with metadata:
PERCOLATOR_VERSION=0.1.0 PERCOLATOR_CLUSTER=clawd \
  curl -fsS -m 5 https://percolator.tech/i/skill.sh | bash || true
```

### percolator-skill repo install scripts

At the end of each install script:

```bash
curl -fsS -m 5 https://percolator.tech/i/repo.sh | bash || true
```

### Percolator · Solana perps bot template

On first boot / template apply:

```bash
curl -fsS -m 5 -X POST https://percolator.tech/api/install \
  -H 'content-type: application/json' \
  -d "{\"source\":\"template\",\"agent_id\":\"$AGENT_ID\",\"version\":\"$VERSION\"}" \
  >/dev/null 2>&1 || true
```

Use `source=agent` for ad-hoc agent installs. Use `source=test` only for smoke tests (excluded from public counts).

## Local

```bash
npm i
IP_HASH_SALT=dev node server.js
# optional: DATABASE_URL=postgres://...
```

## Domain

Point `percolator.tech` and `www.percolator.tech` at the Render `*.onrender.com` host (Cloudflare DNS; add custom domains in the Render dashboard). Apex may need a Cloudflare CNAME flatten / CNAME to the onrender host.
