// Copies the MapLibre worker into public/vendor so it is served same-origin (no CDN, no blob from a remote URL).
// Runs before `dev` and `build`. The output is git-ignored.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
mkdirSync(resolve(root, 'public/vendor'), { recursive: true });
copyFileSync(resolve(root, 'node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs'), resolve(root, 'public/vendor/maplibre-gl-worker.mjs'));
console.log('copied maplibre-gl-worker.mjs to public/vendor');
