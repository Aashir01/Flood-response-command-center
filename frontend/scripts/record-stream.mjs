#!/usr/bin/env node
// Records a real Brain run into the fixture format used by the mock Brain.
//   npm run record -- --brain http://localhost:8000 --name default-demo --lang en [--scenario demo-sindh-2022]
// Writes fixtures/streams/<name>.<lang>.ndjson ({delayMs, seq, event, data} per line),
// fixtures/rest/briefing.<name>.<lang>.json and fixtures/rest/evidence.<name>.<lang>.json.
import { writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (k, d) => {
  const i = argv.indexOf(`--${k}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
};
const brain = arg('brain', 'http://localhost:8000').replace(/\/$/, '');
const name = arg('name', 'default-demo');
const lang = arg('lang', 'en');
const scenario = arg('scenario', 'demo-sindh-2022');
const region = arg('region', 'pk-sindh');
const fixtures = resolve(here, '..', 'fixtures');

const start = await fetch(`${brain}/briefings`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ region, scenario, lang, mode: 'demo' }),
});
if (start.status !== 202) throw new Error(`POST /briefings returned ${start.status}: ${await start.text()}`);
const { briefing_id: id } = await start.json();
console.log(`recording ${id}`);

const res = await fetch(`${brain}/briefings/${id}/events`, { headers: { Accept: 'text/event-stream' } });
const reader = res.body.getReader();
const dec = new TextDecoder();
const frames = [];
let buf = '';
let last = Date.now();
let done = false;
while (!done) {
  const { value, done: end } = await reader.read();
  if (end) break;
  buf += dec.decode(value, { stream: true });
  let idx;
  while ((idx = buf.indexOf('\n\n')) >= 0) {
    const block = buf.slice(0, idx);
    buf = buf.slice(idx + 2);
    const f = {};
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue;
      const c = line.indexOf(':');
      if (c < 0) continue;
      f[line.slice(0, c)] = (f[line.slice(0, c)] ?? '') + line.slice(c + 1).replace(/^ /, '');
    }
    if (!f.event || !f.data) continue;
    const now = Date.now();
    const data = JSON.parse(f.data);
    frames.push({ delayMs: now - last, seq: Number(f.id), event: f.event, data });
    last = now;
    if (f.event === 'briefing' || (f.event === 'error' && data.payload?.fatal)) done = true;
  }
}
reader.cancel().catch(() => {});

const evidence = {};
for (const fr of frames) {
  const runId = fr.data.payload?.run_id;
  if (fr.event !== 'organ_result' || !runId) continue;
  const r = await fetch(`${brain}/evidence/${runId}`);
  if (!r.ok) continue;
  evidence[runId] = {
    organ: fr.data.organ,
    tool: fr.data.tool,
    served_by: fr.data.payload.served_by,
    mode: fr.data.payload.mode,
    node_id: fr.data.task_id,
    generated_at: fr.data.ts,
    doc: await r.json(),
  };
}
const briefing = frames.find((f) => f.event === 'briefing')?.data.payload;
writeFileSync(join(fixtures, 'streams', `${name}.${lang}.ndjson`), frames.map((f) => JSON.stringify(f)).join('\n') + '\n');
if (briefing) writeFileSync(join(fixtures, 'rest', `briefing.${name}.${lang}.json`), JSON.stringify(briefing, null, 1));
writeFileSync(join(fixtures, 'rest', `evidence.${name}.${lang}.json`), JSON.stringify(evidence, null, 1));
console.log(`wrote ${frames.length} frames, ${Object.keys(evidence).length} evidence docs`);
