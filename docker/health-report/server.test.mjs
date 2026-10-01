import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { request } from 'node:http';
import { createHealthServer } from './server.mjs';

const now = Date.parse('2026-10-01T22:50:10Z');
const ready = { httpStatus: 200, body: { status: 'ok', checks: { database: 'up', cache: 'up' } } };
const fixture = () => ({ timestamp: '2026-10-01T22:50:00Z', collectedAt: new Date(now).toISOString(),
  dockerHost: 'unix:///desktop/docker.sock', host: { memory: { totalBytes: 16096243712 } },
  containers: { postgres: { stats: { MemUsage: '46.96MiB / 3.571GiB' } } },
  readiness: ready, errors: [], status: 'ok' });

async function withServer(options, run) {
  const server = createHealthServer({ now: () => now, readSnapshot: async () => JSON.stringify(fixture()),
    checkReadiness: async () => ready, ...options });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try { await run(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test('returns host, container and readiness metrics without caching HTTP response', async () => {
  await withServer({}, async url => {
    const response = await fetch(url + '/health/ready');
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    const body = await response.json();
    assert.equal(body.host.memory.totalBytes, 16096243712);
    assert.equal(body.containers.postgres.stats.MemUsage, '46.96MiB / 3.571GiB');
    assert.equal(body.snapshot.stale, false);
    assert.deepEqual(body.readiness, ready);
  });
});

test('missing and malformed snapshots fail closed; liveness remains independent', async () => {
  for (const readSnapshot of [async () => { throw new Error('missing'); }, async () => '{', async () => '{}']) {
    await withServer({ readSnapshot }, async url => {
      assert.equal((await fetch(url + '/health/live')).status, 200);
      const response = await fetch(url + '/health/ready');
      assert.equal(response.status, 503);
      assert.deepEqual((await response.json()).errors, ['resource_snapshot_unavailable']);
    });
  }
});

test('stale and future-dated snapshots retain metrics and return 503', async () => {
  for (const offset of [-181000, 1000]) {
    const report = fixture(); report.collectedAt = new Date(now + offset).toISOString();
    await withServer({ readSnapshot: async () => JSON.stringify(report) }, async url => {
      const response = await fetch(url + '/health/ready');
      assert.equal(response.status, 503);
      const body = await response.json();
      assert.equal(body.snapshot.stale, true);
      assert.equal(body.host.memory.totalBytes, 16096243712);
      assert.ok(body.errors.includes('resource_snapshot_stale'));
    });
  }
});

test('dependency failures and unavailable readiness return 503 with detail', async () => {
  for (const checkReadiness of [async () => ({ httpStatus: 503, body: { status: 'error', checks: { database: 'down' } } }),
    async () => { throw new Error('connection refused'); }]) {
    await withServer({ checkReadiness }, async url => {
      const response = await fetch(url + '/health/ready');
      assert.equal(response.status, 503);
      assert.equal((await response.json()).status, 'error');
    });
  }
});

test('partial collection cannot become healthy through a successful live probe', async () => {
  const report = fixture(); report.status = 'error'; report.errors = ['redis_diagnostics_unavailable'];
  await withServer({ readSnapshot: async () => JSON.stringify(report) }, async url => {
    const response = await fetch(url + '/health/ready');
    assert.equal(response.status, 503);
    assert.deepEqual((await response.json()).errors, report.errors);
  });
});

test('coalesces readiness probes and rejects writes and unknown routes', async () => {
  let probes = 0;
  await withServer({ checkReadiness: async () => { probes++; return ready; } }, async url => {
    await Promise.all(Array.from({ length: 10 }, () => fetch(url + '/health/ready')));
    assert.equal(probes, 1);
    assert.equal((await fetch(url + '/health/ready', { method: 'POST' })).status, 405);
    assert.equal((await fetch(url + '/other')).status, 404);
  });
});

test('malformed request target does not stop the HTTP server', async () => {
  await withServer({}, async url => {
    const status = await new Promise((resolve, reject) => {
      const req = request(url, { path: 'http://' }, response => {
        response.resume(); resolve(response.statusCode);
      });
      req.on('error', reject); req.end();
    });
    assert.equal(status, 400);
    assert.equal((await fetch(url + '/health/live')).status, 200);
  });
});
