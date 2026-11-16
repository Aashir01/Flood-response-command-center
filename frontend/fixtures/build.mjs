// Regenerates fixtures/streams/*.ndjson and fixtures/rest/*.json. `npm run fixtures`.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SCENARIOS, buildAsk, buildScenario, evals, organList } from './src/scenario.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)));
const streams = join(root, 'streams');
const rest = join(root, 'rest');
mkdirSync(streams, { recursive: true });
mkdirSync(rest, { recursive: true });
const J = (o) => JSON.stringify(o, null, 1);

for (const lang of ['en', 'ur']) {
  for (const name of SCENARIOS) {
    const s = buildScenario({ name, lang });
    writeFileSync(join(streams, `${name}.${lang}.ndjson`), s.stream.map((l) => JSON.stringify(l)).join('\n') + '\n');
    writeFileSync(join(rest, `evidence.${name}.${lang}.json`), J(s.evidence));
    writeFileSync(join(rest, `briefing.${name}.${lang}.json`), J(s.briefing));
  }
  for (const kind of ['answered', 'refused']) {
    const a = buildAsk(kind, lang);
    writeFileSync(join(rest, `ask.${kind}.${lang}.json`), J(a.body));
    writeFileSync(join(rest, `evidence.ask-${kind}.${lang}.json`), J(a.evidence));
  }
}
writeFileSync(join(rest, 'organs.default.json'), J(organList()));
writeFileSync(join(rest, 'organs.voice-cut.json'), J(organList({ voice: 'disabled' })));
writeFileSync(join(rest, 'organs.offline-fallback.json'), J(organList({ live: false })));
for (const k of ['full', 'empty', 'stale', 'partial']) writeFileSync(join(rest, `evals.${k}.json`), J(evals(k)));
console.log('fixtures written');
