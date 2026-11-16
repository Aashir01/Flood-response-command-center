// Builds public/map/{districts,context}.geojson and style.json.
// Uses data/demo/boundaries/pk_districts.geojson when present; otherwise writes the labelled PLACEHOLDER geometry.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { permanentWaterFeature } from './lib/placeholder-geo.mjs';
import { loadFeatures } from './lib/districts.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '..', 'public', 'map');
mkdirSync(out, { recursive: true });

const r4 = (n) => Number(n.toFixed(3));
const roundCoords = (c) => (typeof c[0] === 'number' ? c.map(r4) : c.map(roundCoords));

const { placeholder, features } = loadFeatures();
const centroidOf = (geom) => {
  const flat = JSON.stringify(geom.coordinates).match(/-?\d+\.?\d*/g).map(Number);
  let sx = 0, sy = 0, n = 0;
  for (let i = 0; i < flat.length - 1; i += 2) { sx += flat[i]; sy += flat[i + 1]; n++; }
  return [r4(sx / n), r4(sy / n)];
};
const districts = {
  type: 'FeatureCollection',
  ...(placeholder ? { placeholder: true, note: 'PLACEHOLDER grid cells, not real district borders.' } : { attribution: 'geoBoundaries gbOpen PAK ADM2 (CC BY 4.0), simplified; see data/demo/MANIFEST.md' }),
  features: features.map((f) => ({
    type: 'Feature',
    properties: { district_id: f.properties.district_id, name_en: f.properties.name_en, name_ur: f.properties.name_ur, centroid: f.properties.centroid ?? centroidOf(f.geometry) },
    geometry: { ...f.geometry, coordinates: roundCoords(f.geometry.coordinates) },
  })),
};
const source = placeholder ? 'placeholder' : 'data/demo/boundaries/pk_districts.geojson';
writeFileSync(join(out, 'districts.geojson'), JSON.stringify(districts));

const [w, s, e, n] = [66.0, 23.0, 71.8, 29.0];
const pad = 0.5;
const context = {
  type: 'FeatureCollection',
  placeholder: true,
  note: 'PLACEHOLDER context frame and permanent-water strip. Real Natural Earth context and the permanent-water reference come with the demo dataset.',
  features: [
    { type: 'Feature', properties: { kind: 'frame', placeholder: true }, geometry: { type: 'Polygon', coordinates: [[[w - pad, s - pad], [e + pad, s - pad], [e + pad, n + pad], [w - pad, n + pad], [w - pad, s - pad]]] } },
    permanentWaterFeature(),
  ],
};
writeFileSync(join(out, 'context.geojson'), JSON.stringify(context));

const style = {
  version: 8,
  name: 'stitch-ouija',
  sources: {
    context: { type: 'geojson', data: '/map/context.geojson' },
    districts: { type: 'geojson', data: '/map/districts.geojson' },
    flood: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    reference: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    allocation: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#07090c' } },
    { id: 'context-fill', type: 'fill', source: 'context', filter: ['==', ['get', 'kind'], 'frame'], paint: { 'fill-color': '#0d1217' } },
    { id: 'water-perm', type: 'fill', source: 'context', filter: ['==', ['get', 'kind'], 'permanent_water'], paint: { 'fill-color': '#2a6f68', 'fill-opacity': 0.55 } },
    { id: 'flood-fill', type: 'fill', source: 'flood', paint: { 'fill-color': '#2cf5c0', 'fill-opacity': 0.45 } },
    { id: 'flood-glow-outer', type: 'line', source: 'flood', paint: { 'line-color': '#2cf5c0', 'line-width': 10, 'line-blur': 8, 'line-opacity': 0.25 } },
    { id: 'flood-glow-mid', type: 'line', source: 'flood', paint: { 'line-color': '#2cf5c0', 'line-width': 5, 'line-blur': 3, 'line-opacity': 0.45 } },
    { id: 'flood-edge', type: 'line', source: 'flood', paint: { 'line-color': '#2cf5c0', 'line-width': 1.2, 'line-opacity': 0.95 } },
    { id: 'districts-line', type: 'line', source: 'districts', paint: { 'line-color': '#e8dfc8', 'line-width': 0.8, 'line-opacity': 0.7 } },
    { id: 'reference-line', type: 'line', source: 'reference', paint: { 'line-color': '#e8dfc8', 'line-width': 1.2, 'line-dasharray': [2, 2], 'line-opacity': 0.9 } },
    { id: 'allocation-circles', type: 'circle', source: 'allocation', paint: { 'circle-color': '#ff9d3c', 'circle-opacity': 0.55, 'circle-stroke-color': '#ff9d3c', 'circle-stroke-width': 1.5, 'circle-radius': ['*', ['get', 'k'], ['sqrt', ['get', 'people_covered']]] } },
  ],
};
writeFileSync(join(out, 'style.json'), JSON.stringify(style, null, 2));
console.log(`map assets written (districts from ${source})`);