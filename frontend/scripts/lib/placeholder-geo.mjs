// PLACEHOLDER geometry for the demo scene. Twelve rough grid cells over Sindh, NOT real district borders.
// Used until data/demo/boundaries/pk_districts.geojson exists (owned by the ledger spec). Deterministic.
export const DISTRICTS = [
  { id: 'pk-sindh-jacobabad', en: 'Jacobabad', ur: 'جیکب آباد', col: 0, row: 3 },
  { id: 'pk-sindh-sukkur', en: 'Sukkur', ur: 'سکھر', col: 1, row: 3 },
  { id: 'pk-sindh-ghotki', en: 'Ghotki', ur: 'گھوٹکی', col: 2, row: 3 },
  { id: 'pk-sindh-larkana', en: 'Larkana', ur: 'لاڑکانہ', col: 0, row: 2 },
  { id: 'pk-sindh-khairpur', en: 'Khairpur', ur: 'خیرپور', col: 1, row: 2 },
  { id: 'pk-sindh-mirpurkhas', en: 'Mirpurkhas', ur: 'میرپورخاص', col: 2, row: 2 },
  { id: 'pk-sindh-dadu', en: 'Dadu', ur: 'دادو', col: 0, row: 1 },
  { id: 'pk-sindh-shaheed-benazirabad', en: 'Shaheed Benazirabad', ur: 'شہید بینظیر آباد', col: 1, row: 1 },
  { id: 'pk-sindh-sanghar', en: 'Sanghar', ur: 'سانگھڑ', col: 2, row: 1 },
  { id: 'pk-sindh-hyderabad', en: 'Hyderabad', ur: 'حیدرآباد', col: 0, row: 0 },
  { id: 'pk-sindh-badin', en: 'Badin', ur: 'بدین', col: 1, row: 0 },
  { id: 'pk-sindh-thatta', en: 'Thatta', ur: 'ٹھٹھہ', col: 2, row: 0 },
];

const LON = [66.9, 68.1, 69.3, 70.5];
const LAT = [23.9, 25.1, 26.3, 27.5, 28.6];

function jitter(i, j) {
  // deterministic pseudo-random offsets in [-0.18, 0.18]
  const h = Math.sin(i * 12.9898 + j * 78.233) * 43758.5453;
  const f = h - Math.floor(h);
  const g = Math.sin(i * 39.346 + j * 11.135) * 24634.6345;
  const k = g - Math.floor(g);
  return [(f - 0.5) * 0.36, (k - 0.5) * 0.36];
}
const vertex = (i, j) => {
  const edge = i === 0 || j === 0 || i === LON.length - 1 || j === LAT.length - 1;
  const [dx, dy] = edge ? [0, 0] : jitter(i, j);
  return [Number((LON[i] + dx).toFixed(4)), Number((LAT[j] + dy).toFixed(4))];
};

export function cellRing(col, row) {
  return [vertex(col, row), vertex(col + 1, row), vertex(col + 1, row + 1), vertex(col, row + 1), vertex(col, row)];
}
export function centroid(ring) {
  const pts = ring.slice(0, -1);
  return [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length].map((v) => Number(v.toFixed(4)));
}
export function districtFeatures() {
  return DISTRICTS.map((d) => {
    const ring = cellRing(d.col, d.row);
    return {
      type: 'Feature',
      properties: { district_id: d.id, name_en: d.en, name_ur: d.ur, centroid: centroid(ring), placeholder: true },
      geometry: { type: 'Polygon', coordinates: [ring] },
    };
  });
}
/** A blob inside a district cell: shrunken ring around the centroid. `scale` in (0,1], `seed` rotates the shape. */
export function blobIn(districtId, scale, seed = 0) {
  const d = DISTRICTS.find((x) => x.id === districtId);
  if (!d) throw new Error(`unknown district ${districtId}`);
  const ring = cellRing(d.col, d.row).slice(0, -1);
  const c = centroid([...ring, ring[0]]);
  const pts = ring.map((p, i) => {
    const wob = 0.82 + 0.18 * Math.sin(i * 2.1 + seed);
    return [Number((c[0] + (p[0] - c[0]) * scale * wob).toFixed(4)), Number((c[1] + (p[1] - c[1]) * scale * wob).toFixed(4))];
  });
  // add midpoints for a rounder look
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    out.push(a, [Number(((a[0] + b[0]) / 2 + 0.05 * Math.cos(i + seed)).toFixed(4)), Number(((a[1] + b[1]) / 2 + 0.05 * Math.sin(i + seed)).toFixed(4))]);
  }
  out.push(out[0]);
  return { type: 'Polygon', coordinates: [out] };
}
/** Placeholder permanent-water strip meandering north-south through the middle (an Indus-like band). */
export function permanentWaterFeature() {
  const left = [];
  const right = [];
  for (let k = 0; k <= 16; k++) {
    const lat = 23.9 + (k / 16) * (28.6 - 23.9);
    const lon = 68.55 + 0.45 * Math.sin(k * 0.55);
    left.push([Number((lon - 0.045).toFixed(4)), Number(lat.toFixed(4))]);
    right.push([Number((lon + 0.045).toFixed(4)), Number(lat.toFixed(4))]);
  }
  return { type: 'Feature', properties: { kind: 'permanent_water', placeholder: true }, geometry: { type: 'Polygon', coordinates: [[...left, ...right.reverse(), left[0]]] } };
}
export const BBOX = [LON[0], LAT[0], LON[LON.length - 1], LAT[LAT.length - 1]];