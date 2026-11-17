#!/usr/bin/env node
// Mock Brain: replays committed fixtures over the Brain HTTP/SSE API (mcp-contracts.md section 8c).
// Node built-ins only. Usage:
//   node mock-brain/server.mjs [--port 8787] [--static out] [--scenario default-demo] [--speed 1]
// Routes are served under /api (same origin as the static export, like Caddy in Compose).
// Test hooks (mock only): POST /__mock/config {scenario?, speed?, evals?}, GET /__mock/config.
import { createServer } from 'node:http';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { extname, join, normalize, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = resolve(here, '..', 'fixtures');

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : 'true']);
    return acc;
  }, []),
);
const PORT = Number(args.port ?? process.env.PORT ?? 8787);
const STATIC_DIR = args.static ? resolve(process.cwd(), args.static) : null;

/** Scenarios: name -> stream fixture, organ list fixture, extra behaviour. */
export const SCENARIOS = {
  'default-demo': { stream: 'default-demo', organs: 'default' },
  conflict: { stream: 'conflict', organs: 'default' },
  'organ-error': { stream: 'organ-error', organs: 'default' },
  refusal: { stream: 'refusal', organs: 'default' },
  partial: { stream: 'partial', organs: 'default' },
  slow: { stream: 'default-demo', organs: 'default', speedFactor: 0.5 },
  'voice-cut': { stream: 'default-demo', organs: 'voice-cut', voiceCut: true },
  'offline-fallback': { stream: 'offline-fallback', organs: 'offline-fallback' },
  'brain-down': { down: true },
};

const config = {
  scenario: SCENARIOS[args.scenario] ? args.scenario : 'default-demo',
  speed: Number(args.speed ?? 1) || 1,
  evals: 'full',
};

const cache = new Map();
function fixture(rel) {
  if (!cache.has(rel)) {
    const p = join(fixtures, rel);
    cache.set(rel, existsSync(p) ? readFileSync(p, 'utf8') : null);
  }
  return cache.get(rel);
}
const json = (rel) => {
  const s = fixture(rel);
  return s === null ? null : JSON.parse(s);
};
function stream(name, lang) {
  const s = fixture(`streams/${name}.${lang}.ndjson`);
  return s ? s.trim().split('\n').map((l) => JSON.parse(l)) : [];
}

/** briefing_id -> run record */
const runs = new Map();
const MAX_RUNS = 200;

function send(res, status, body, headers = {}) {
  const data = body === undefined ? '' : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  res.end(data);
}
const apiError = (res, status, code, message, headers) => send(res, status, { error: { code, message } }, headers);

function readBody(req, limit = 4 * 1024 * 1024) {
  return new Promise((resolveBody, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(Object.assign(new Error('too large'), { code: 'PAYLOAD_TOO_LARGE' }));
        req.destroy();
      } else chunks.push(c);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw) return resolveBody({});
      try {
        resolveBody(JSON.parse(raw));
      } catch {
        reject(Object.assign(new Error('invalid JSON'), { code: 'INVALID_INPUT' }));
      }
    });
    req.on('error', reject);
  });
}

/** RFC 6901 pointer resolution. Returns {found, value}. */
export function resolvePointer(doc, pointer) {
  if (pointer === '' || pointer === '/') return { found: pointer === '', value: doc };
  if (!pointer.startsWith('/')) return { found: false };
  let cur = doc;
  for (const raw of pointer.slice(1).split('/')) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (cur !== null && typeof cur === 'object' && Object.prototype.hasOwnProperty.call(cur, key)) cur = cur[key];
    else return { found: false };
  }
  return { found: true, value: cur };
}

function scenarioFor(req, body) {
  const header = req.headers['x-mock-scenario'];
  let name = typeof header === 'string' && SCENARIOS[header] ? header : config.scenario;
  // The mock has no network: a live request on the default scenario falls back to demo, as the Brain would offline.
  if (body?.mode === 'live' && name === 'default-demo') name = 'offline-fallback';
  return name;
}

function streamDurationMs(frames, speed) {
  return frames.reduce((t, f) => t + (f.delayMs ?? 0), 0) / speed;
}

function patchFrame(frame, run) {
  if (frame.event !== 'briefing') return frame.data;
  return { ...frame.data, payload: { ...frame.data.payload, briefing_id: run.id } };
}

function briefingOf(run) {
  const last = run.frames.find((f) => f.event === 'briefing');
  return last ? patchFrame(last, run).payload : undefined;
}

function runStatus(run, now = Date.now()) {
  if (run.cancelled) return 'cancelled';
  return now - run.startedAt >= run.durationMs ? 'done' : 'running';
}

function writeFrame(res, id, event, data) {
  res.write(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function handleEvents(req, res, run, url) {
  const headerId = req.headers['last-event-id'];
  const q = url.searchParams.get('last_event_id');
  if (q !== null && !/^\d+$/.test(q)) return apiError(res, 400, 'INVALID_INPUT', 'last_event_id must be a non-negative integer');
  const lastId = Number(q ?? headerId ?? 0) || 0;
  const dropAfter = url.searchParams.has('drop_after') ? Number(url.searchParams.get('drop_after')) : Infinity;
  const speed = Number(url.searchParams.get('speed') ?? 0) || run.speed;

  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-store',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write('retry: 2000\n\n');
  const ping = setInterval(() => res.write(': ping\n\n'), 15_000);
  const timers = new Set();
  let sent = 0;
  let ended = false;
  const end = () => {
    if (ended) return;
    ended = true;
    clearInterval(ping);
    for (const t of timers) clearTimeout(t);
    run.listeners.delete(onCancel);
    res.end();
  };
  req.on('close', end);

  const onCancel = (seq) => {
    if (ended) return;
    writeFrame(res, seq, 'error', {
      event: 'error',
      ts: new Date().toISOString(),
      task_id: 'run',
      payload: { code: 'CANCELLED', message: 'The run was cancelled.', fatal: true, retryable: false },
    });
    end();
  };
  run.listeners.add(onCancel);

  if (run.cancelled) {
    if (run.cancelSeq > lastId) onCancel(run.cancelSeq);
    else end();
    return;
  }

  // Each frame is due at startedAt + cumulative delay / speed; frames already due are sent at once (stored replay).
  let due = 0;
  for (const f of run.frames) {
    due += (f.delayMs ?? 0) / speed;
    if (f.seq <= lastId) continue;
    const wait = Math.max(0, run.startedAt + due - Date.now());
    const t = setTimeout(() => {
      timers.delete(t);
      if (ended || run.cancelled) return;
      writeFrame(res, f.seq, f.event, patchFrame(f, run));
      sent += 1;
      if (f.event === 'briefing') return end();
      if (sent >= dropAfter) {
        // Simulated network drop: destroy without a clean end.
        clearInterval(ping);
        ended = true;
        res.destroy();
      }
    }, wait);
    timers.add(t);
  }
}

/** A short, quiet synthesized WAV (16 kHz mono 16-bit) standing in for TTS audio. */
function toneWav(seconds = 1.6) {
  const rate = 16000;
  const n = Math.floor(rate * seconds);
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write('WAVEfmt ', 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const env = Math.min(1, t * 8) * Math.min(1, (seconds - t) * 8);
    const s = 0.18 * env * (Math.sin(2 * Math.PI * 196 * t) * 0.7 + Math.sin(2 * Math.PI * 294 * t) * 0.3);
    buf.writeInt16LE(Math.round(s * 32767), 44 + i * 2);
  }
  return { b64: buf.toString('base64'), duration: seconds, rate };
}

const ASK_ANSWERABLE = /water|drink|litre|liter|پانی/i;
const URDU_SCRIPT = /[\u0600-\u06FF]/;
const ttsCache = new Set();

async function handleApi(req, res, url) {
  const path = url.pathname.replace(/^\/api/, '') || '/';
  const sc = SCENARIOS[config.scenario];
  if (sc.down && !path.startsWith('/healthz')) {
    // Connection refused, as close as a running server can get.
    req.socket.destroy();
    return;
  }
  const method = req.method ?? 'GET';

  if (path === '/healthz' && method === 'GET') return send(res, 200, { status: 'ok', organs_ready: 5, db_ok: true });

  if (path === '/organs' && method === 'GET') {
    const name = req.headers['x-mock-scenario'] && SCENARIOS[req.headers['x-mock-scenario']] ? req.headers['x-mock-scenario'] : config.scenario;
    return send(res, 200, json(`rest/organs.${SCENARIOS[name].organs}.json`));
  }

  if (path === '/briefings' && method === 'POST') {
    let body;
    try {
      body = await readBody(req, 64 * 1024);
    } catch (e) {
      return apiError(res, e.code === 'PAYLOAD_TOO_LARGE' ? 413 : 400, e.code, e.message);
    }
    if (typeof body.region !== 'string' || !/^[a-z0-9-]{1,64}$/.test(body.region) || typeof body.scenario !== 'string')
      return apiError(res, 422, 'INVALID_INPUT', 'region (slug) and scenario are required');
    const lang = body.lang === 'ur' ? 'ur' : 'en';
    const name = scenarioFor(req, body);
    const scen = SCENARIOS[name];
    const id = randomUUID();
    const speed = config.speed * (scen.speedFactor ?? 1);
    const frames = stream(scen.stream, lang);
    const run = {
      id,
      name,
      lang,
      request: { region: body.region, scenario: body.scenario, lang, mode: body.mode === 'live' ? 'live' : 'demo' },
      frames,
      speed,
      startedAt: Date.now(),
      durationMs: streamDurationMs(frames, speed),
      evidence: json(`rest/evidence.${scen.stream}.${lang}.json`) ?? {},
      createdAt: new Date().toISOString(),
      cancelled: false,
      listeners: new Set(),
    };
    runs.set(id, run);
    if (runs.size > MAX_RUNS) runs.delete(runs.keys().next().value);
    return send(res, 202, {
      briefing_id: id,
      task_id: id,
      status: 'running',
      events_url: `/api/briefings/${id}/events`,
      result_url: `/api/briefings/${id}`,
    });
  }

  const bm = path.match(/^\/briefings\/([0-9a-f-]{36})(\/events)?$/);
  if (bm) {
    const run = runs.get(bm[1]);
    if (!run) return apiError(res, 404, 'NOT_FOUND', 'No such briefing');
    if (bm[2] && method === 'GET') return handleEvents(req, res, run, url);
    if (!bm[2] && method === 'DELETE') {
      if (!run.cancelled && runStatus(run) === 'running') {
        run.cancelled = true;
        const sentSoFar = run.frames.filter((f, i, all) => all.slice(0, i + 1).reduce((t, x) => t + (x.delayMs ?? 0) / run.speed, 0) <= Date.now() - run.startedAt);
        run.cancelSeq = (sentSoFar.at(-1)?.seq ?? 0) + 1;
        for (const l of [...run.listeners]) l(run.cancelSeq);
      }
      res.writeHead(202);
      return res.end();
    }
    if (!bm[2] && method === 'GET') {
      const status = runStatus(run);
      return send(res, 200, {
        briefing_id: run.id,
        status,
        request: run.request,
        created_at: run.createdAt,
        finished_at: status === 'done' ? new Date(run.startedAt + run.durationMs).toISOString() : null,
        briefing: status === 'done' ? briefingOf(run) : null,
        error: status === 'cancelled' ? { code: 'CANCELLED', message: 'The run was cancelled.' } : null,
      });
    }
  }

  const em = path.match(/^\/evidence\/([^/]+)$/);
  if (em && method === 'GET') {
    const runId = decodeURIComponent(em[1]);
    let entry;
    for (const r of [...runs.values()].reverse()) if (r.evidence[runId]) { entry = r.evidence[runId]; break; }
    if (!entry) for (const f of ['ask-answered', 'ask-refused']) for (const l of ['en', 'ur']) entry ??= json(`rest/evidence.${f}.${l}.json`)?.[runId];
    if (!entry) for (const s of Object.values(SCENARIOS)) if (s.stream) entry ??= json(`rest/evidence.${s.stream}.en.json`)?.[runId];
    if (!entry) return apiError(res, 404, 'NOT_FOUND', 'Unknown run id');
    const pointer = url.searchParams.get('pointer');
    if (pointer === null) return send(res, 200, entry.doc);
    const r = resolvePointer(entry.doc, pointer);
    if (!r.found) return apiError(res, 404, 'NOT_FOUND', 'Pointer does not resolve');
    return send(res, 200, {
      ref: { run_id: runId, organ: entry.organ, tool: entry.tool, json_pointer: pointer },
      value: r.value,
      organ: entry.organ,
      tool: entry.tool,
      served_by: entry.served_by ?? 'real',
      mode: entry.mode ?? 'demo',
      generated_at: entry.generated_at,
      node_id: entry.node_id ?? null,
    });
  }

  if (path === '/ask' && method === 'POST') {
    let body;
    try {
      body = await readBody(req, 16 * 1024);
    } catch (e) {
      return apiError(res, 400, 'INVALID_INPUT', e.message);
    }
    const q = typeof body.question === 'string' ? body.question.trim() : '';
    if (!q || q.length > 500) return apiError(res, 422, 'INVALID_INPUT', 'question must be 1 to 500 characters');
    const lang = body.lang === 'ur' || body.lang === 'en' ? body.lang : URDU_SCRIPT.test(q) ? 'ur' : 'en';
    const kind = config.scenario === 'refusal' || !ASK_ANSWERABLE.test(q) ? 'refused' : 'answered';
    await new Promise((r) => setTimeout(r, 300 / config.speed));
    return send(res, 200, json(`rest/ask.${kind}.${lang}.json`));
  }

  if (path === '/voice/speak' && method === 'POST') {
    if (sc.voiceCut) return apiError(res, 503, 'UPSTREAM_UNAVAILABLE', 'Voice is disabled in this deployment');
    let body;
    try {
      body = await readBody(req, 64 * 1024);
    } catch (e) {
      return apiError(res, 400, 'INVALID_INPUT', e.message);
    }
    if (!body.briefing_id && !body.text) return apiError(res, 422, 'INVALID_INPUT', 'briefing_id is required');
    if (body.text && !body.briefing_id) return apiError(res, 422, 'INVALID_INPUT', 'arbitrary text is disabled (STITCH_ALLOW_ARBITRARY_TTS is off)');
    const lang = body.lang === 'ur' ? 'ur' : 'en';
    const key = `${body.briefing_id}:${lang}`;
    const synthesized = ttsCache.has(key) ? 'cache' : 'live';
    ttsCache.add(key);
    const w = toneWav();
    return send(res, 200, {
      audio_b64: w.b64,
      format: 'wav',
      duration_s: w.duration,
      sample_rate: w.rate,
      lang,
      provider: 'azure',
      synthesized,
      voice: lang === 'ur' ? 'ur-PK-UzmaNeural' : 'en-GB-SoniaNeural',
      served_by: 'recorded',
    });
  }

  if (path === '/voice/transcribe' && method === 'POST') {
    if (sc.voiceCut) return apiError(res, 503, 'UPSTREAM_UNAVAILABLE', 'Voice is disabled in this deployment');
    let body;
    try {
      body = await readBody(req, 4 * 1024 * 1024);
    } catch (e) {
      return apiError(res, e.code === 'PAYLOAD_TOO_LARGE' ? 413 : 400, e.code, e.message);
    }
    if (typeof body.audio_b64 !== 'string' || !body.audio_b64) return apiError(res, 422, 'INVALID_INPUT', 'audio_b64 is required');
    const ur = body.lang_hint === 'ur';
    const text = ur ? 'ہر شخص کو روزانہ کتنا پینے کا پانی چاہیے؟' : 'How much drinking water does each person need per day?';
    return send(res, 200, {
      text,
      lang: ur ? 'ur' : 'en',
      segments: [{ start: 0, end: 2.4, text }],
      lang_confidence: 0.91,
      served_by: 'recorded',
    });
  }

  if (path === '/evals/latest' && method === 'GET') return send(res, 200, json(`rest/evals.${config.evals}.json`) ?? { generated_at: null, organs: {} });

  return apiError(res, 404, 'NOT_FOUND', `No route ${method} ${path}`);
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.geojson': 'application/geo+json; charset=utf-8',
  '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
};

function serveStatic(req, res, url) {
  if (!STATIC_DIR) return apiError(res, 404, 'NOT_FOUND', 'static serving is off (pass --static out)');
  let p = decodeURIComponent(url.pathname);
  if (p === '/') {
    res.writeHead(302, { Location: '/en/' });
    return res.end();
  }
  const safe = normalize(join(STATIC_DIR, p));
  if (!safe.startsWith(STATIC_DIR)) return apiError(res, 403, 'INVALID_INPUT', 'forbidden');
  let file = safe;
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html');
  else if (!existsSync(file) && existsSync(`${file}.html`)) file = `${file}.html`;
  if (!existsSync(file)) {
    const nf = join(STATIC_DIR, '404.html');
    res.writeHead(404, { 'Content-Type': MIME['.html'] });
    return res.end(existsSync(nf) ? readFileSync(nf) : 'not found');
  }
  const immutable = p.startsWith('/_next/static/');
  res.writeHead(200, {
    'Content-Type': MIME[extname(file)] ?? 'application/octet-stream',
    'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'no-cache',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(readFileSync(file));
}

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Last-Event-ID, X-Mock-Scenario',
  'Access-Control-Max-Age': '600',
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  // Dev only: the Next dev server runs on another port, so the mock answers cross-origin requests.
  for (const [k, v] of Object.entries(CORS)) res.setHeader(k, v);
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }
  try {
    if (url.pathname === '/__mock/config') {
      if (req.method === 'POST') {
        const b = await readBody(req, 4096);
        if (b.scenario && SCENARIOS[b.scenario]) config.scenario = b.scenario;
        if (b.speed) config.speed = Number(b.speed) || config.speed;
        if (b.evals && ['full', 'empty', 'stale', 'partial'].includes(b.evals)) config.evals = b.evals;
      }
      return send(res, 200, { ...config, scenarios: Object.keys(SCENARIOS) });
    }
    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return await handleApi(req, res, url);
    return serveStatic(req, res, url);
  } catch (e) {
    if (!res.headersSent) apiError(res, 500, 'INTERNAL', String(e?.message ?? e));
    else res.end();
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`mock Brain on http://127.0.0.1:${PORT}/api (scenario ${config.scenario}, speed ${config.speed})${STATIC_DIR ? `, static ${STATIC_DIR}` : ''}`);
});
