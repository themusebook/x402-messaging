import { createServer, createMemoryStore } from './app.js';

let store;
if (process.env.REDIS_URL) {
  store = await (await import('./store-redis.js')).createRedisStore(process.env.REDIS_URL);
  console.log('store: redis');
} else if (process.env.DATABASE_URL) {
  store = await (await import('./store-pg.js')).createPgStore(process.env.DATABASE_URL);
  console.log('store: postgres');
} else {
  store = createMemoryStore();
  console.warn('DATABASE_URL/REDIS_URL not set: using in-memory store');
}

const port = Number(process.env.PORT || 10000);
createServer(store, {
  ipSalt: process.env.IP_HASH_SALT || 'dev-only-change-me',
  marketsUrl: process.env.MARKETS_URL || 'https://percolator.clawdchain.trade/api/markets',
}).listen(port, '0.0.0.0', () => {
  console.log(`percolator-tech on :${port}`);
});
