#!/usr/bin/env node
// `npm run dev:mock`: the mock Brain on :8787 plus `next dev` pointed at it through NEXT_PUBLIC_BRAIN_URL.
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const MOCK_PORT = process.env.MOCK_PORT ?? '8787';
const extra = process.argv.slice(2);
const procs = [
  spawn(process.execPath, ['mock-brain/server.mjs', '--port', MOCK_PORT, ...extra], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, [resolve(root, 'node_modules/next/dist/bin/next'), 'dev'], {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, NEXT_PUBLIC_BRAIN_URL: process.env.NEXT_PUBLIC_BRAIN_URL ?? `http://127.0.0.1:${MOCK_PORT}/api` },
  }),
];
const stop = () => {
  for (const p of procs) p.kill();
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
for (const p of procs) p.on('exit', (code) => code && stop());
