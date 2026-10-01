import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export function createHealthServer({
  readSnapshot = () => readFile(process.env.HEALTH_REPORT_PATH || '/data/health.json', 'utf8'),
  now = Date.now,
  maxAgeSeconds = Number(process.env.HEALTH_REPORT_MAX_AGE_SECONDS || 180),
  checkReadiness = async () => {
    const response = await fetch(process.env.BACKEND_HEALTH_URL || 'http://backend:3000/health/ready',
      { signal: AbortSignal.timeout(4000) });
    return { httpStatus: response.status, body: await response.json() };
  },
} = {}) {
  if (!Number.isFinite(maxAgeSeconds) || maxAgeSeconds <= 0) throw new Error('Invalid report age limit');
  // Share simultaneous requests and keep dependency probes bounded under polling.
  let probe, probeExpires = 0;
  const readiness = () => {
    if (!probe || now() >= probeExpires) {
      probeExpires = now() + 5000;
      probe = Promise.resolve().then(checkReadiness).catch(() => null);
    }
    return probe;
  };
  return createServer(async (request, response) => {
    response.setHeader('Content-Type', 'application/json; charset=utf-8');
    response.setHeader('Cache-Control', 'no-store');
    const send = (code, body) => { response.writeHead(code); response.end(JSON.stringify(body)); };
    let path;
    try { path = new URL(request.url, 'http://localhost').pathname; }
    catch { return send(400, { status: 'error' }); }
    if (request.method !== 'GET') {
      response.setHeader('Allow', 'GET');
      return send(405, { status: 'error' });
    }
    if (path === '/health/live') return send(200, { status: 'ok' });
    if (path !== '/health/ready') return send(404, { status: 'error' });
    let report;
    try {
      report = JSON.parse(await readSnapshot());
      if (!report || !Array.isArray(report.errors) || !report.host || !report.containers ||
          !['ok', 'error'].includes(report.status) || !Number.isFinite(Date.parse(report.collectedAt))) {
        throw new Error('Invalid report');
      }
    } catch {
      return send(503, { status: 'error', host: {}, containers: {}, readiness: null,
        errors: ['resource_snapshot_unavailable'], snapshot: { stale: true, maxAgeSeconds } });
    }
    const ageSeconds = (now() - Date.parse(report.collectedAt)) / 1000;
    const stale = ageSeconds < 0 || ageSeconds > maxAgeSeconds;
    const sampledStatus = report.status;
    report.snapshot = { collectedAt: report.collectedAt, ageSeconds: Math.round(ageSeconds),
      maxAgeSeconds, stale };
    delete report.collectedAt;
    if (stale) report.errors.push('resource_snapshot_stale');
    report.readiness = await readiness();
    if (!report.readiness) report.errors.push('readiness_unavailable');
    report.status = sampledStatus === 'ok' && !report.errors.length &&
      report.readiness?.httpStatus === 200 && report.readiness?.body?.status === 'ok' ? 'ok' : 'error';
    return send(report.status === 'ok' ? 200 : 503, report);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  createHealthServer().listen(8080, '0.0.0.0');
}
