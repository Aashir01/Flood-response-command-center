// Loads the demo district boundaries (owned by the ledger spec) and adds Urdu names.
// Falls back to the labelled PLACEHOLDER grid when data/demo/boundaries/pk_districts.geojson is missing.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DISTRICTS as PLACEHOLDER, cellRing, districtFeatures } from './placeholder-geo.mjs';

const here = dirname(fileURLToPath(import.meta.url));
export const REAL_PATH = resolve(here, '..', '..', '..', 'data', 'demo', 'boundaries', 'pk_districts.geojson');

export const URDU_NAMES = {
  'pk-sindh-badin': 'بدین', 'pk-sindh-dadu': 'دادو', 'pk-sindh-ghotki': 'گھوٹکی', 'pk-sindh-hyderabad': 'حیدرآباد',
  'pk-sindh-jacobabad': 'جیکب آباد', 'pk-sindh-jamshoro': 'جامشورو', 'pk-sindh-karachi': 'کراچی', 'pk-sindh-kashmore': 'کشمور',
  'pk-sindh-khairpur': 'خیرپور', 'pk-sindh-matiari': 'مٹیاری', 'pk-sindh-mirpur-khas': 'میرپور خاص', 'pk-sindh-naushahro-feroze': 'نوشہرو فیروز',
  'pk-sindh-nawabshah': 'نواب شاہ (شہید بینظیر آباد)', 'pk-sindh-qambar-shahdadkot': 'قمبر شہداد کوٹ', 'pk-sindh-sanghar': 'سانگھڑ',
  'pk-sindh-shikarpur': 'شکارپور', 'pk-sindh-sukkur': 'سکھر', 'pk-sindh-tando-allahyar': 'ٹنڈو الہ یار', 'pk-sindh-tando-muhammad-khan': 'ٹنڈو محمد خان',
  'pk-sindh-tharparkar': 'تھرپارکر', 'pk-sindh-thatta': 'ٹھٹھہ', 'pk-sindh-umerkot': 'عمرکوٹ',
};

export function loadFeatures() {
  if (existsSync(REAL_PATH)) {
    const raw = JSON.parse(readFileSync(REAL_PATH, 'utf8'));
    return { placeholder: false, features: raw.features.map((f) => ({ ...f, properties: { ...f.properties, name_en: f.properties.name, name_ur: URDU_NAMES[f.properties.district_id] ?? f.properties.name } })) };
  }
  return { placeholder: true, features: districtFeatures() };
}

const ringArea = (r) => {
  let a = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += r[j][0] * r[i][1] - r[i][0] * r[j][1];
  return Math.abs(a / 2);
};
export function largestRing(geom) {
  const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
  let best = null;
  for (const p of polys) if (!best || ringArea(p[0]) > ringArea(best)) best = p[0];
  return best;
}
export const meanPoint = (ring) => {
  const pts = ring.slice(0, -1);
  return [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
};

export function loadDistricts() {
  const { placeholder, features } = loadFeatures();
  return {
    placeholder,
    list: features.map((f) => ({ id: f.properties.district_id, en: f.properties.name_en, ur: f.properties.name_ur, ring: largestRing(f.geometry) })),
  };
}

/** A smaller wobbly copy of a district's largest ring, shrunk toward its mean point. Fixture use only. */
export function blobOf(ring, scale, seed = 0) {
  const c = meanPoint(ring);
  const step = Math.max(1, Math.floor((ring.length - 1) / 14));
  const pts = [];
  for (let i = 0; i < ring.length - 1; i += step) {
    const wob = 0.8 + 0.2 * Math.sin(i * 1.7 + seed);
    pts.push([Number((c[0] + (ring[i][0] - c[0]) * scale * wob).toFixed(4)), Number((c[1] + (ring[i][1] - c[1]) * scale * wob).toFixed(4))]);
  }
  pts.push(pts[0]);
  return { type: 'Polygon', coordinates: [pts] };
}
export { cellRing, PLACEHOLDER };