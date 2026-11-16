// Hand-authored, contract-shaped demo data for the Sindh Aug 2022 scene. Every ToolResult is
// marked as a fixture (data source id `fixture-hand-authored`) and validated against the JSON Schemas
// by tests/unit/fixtures.contract.test.ts. Replace with recorded streams via `npm run record`.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { blobOf, loadDistricts } from '../../scripts/lib/districts.mjs';

export const CONTRACT_VERSION = '0.4';
export const T0 = Date.parse('2026-11-20T10:00:00Z');
export const iso = (ms) => new Date(T0 + ms).toISOString().replace('.000Z', 'Z');

export function uid(name) {
  const h = createHash('sha1').update(`stitch-fixture:${name}`).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-8${h.slice(17, 20)}-${h.slice(20, 32)}`;
}
const sha = (s) => createHash('sha256').update(s).digest('hex');

export const FIXTURE_SOURCE = { id: 'fixture-hand-authored', name: 'Hand-authored UI fixture (not a live organ output)', license: 'MIT (this repository)', as_of: '2026-11-20' };

export function toolResult(organ, tool, data, { ok = true, error = null, mode = 'demo', warnings = [], runName, sources = [FIXTURE_SOURCE], model = null, at = 0 } = {}) {
  return {
    ok,
    data: ok ? data : null,
    error: ok ? null : error,
    provenance: {
      organ,
      tool,
      tool_version: '0.1.0',
      contract_version: CONTRACT_VERSION,
      run_id: uid(runName ?? `${organ}.${tool}`),
      inputs_hash: sha(`${organ}.${tool}`),
      mode,
      data_sources: sources,
      model,
      generated_at: iso(at),
    },
    warnings: ['FIXTURE: hand-authored for UI development, not a live organ call', ...warnings],
  };
}

// ---------- district table (ledger resource) ----------
// Rows are a snapshot of data/demo/ledger/districts.parquet (22 Sindh districts), joined with the boundary geometry.
const snapshot = JSON.parse(readFileSync(new URL('./ledger-districts.snapshot.json', import.meta.url), 'utf8'));
const { list: geoList } = loadDistricts();
// Hand-authored flooded fractions for the demo scene (fixture values, not model output).
const FLOOD_FRACTION = {
  'pk-sindh-dadu': 0.42, 'pk-sindh-qambar-shahdadkot': 0.33, 'pk-sindh-jamshoro': 0.2, 'pk-sindh-jacobabad': 0.2, 'pk-sindh-badin': 0.18,
  'pk-sindh-tando-muhammad-khan': 0.16, 'pk-sindh-matiari': 0.14, 'pk-sindh-sanghar': 0.12, 'pk-sindh-shikarpur': 0.12, 'pk-sindh-naushahro-feroze': 0.12,
  'pk-sindh-khairpur': 0.1, 'pk-sindh-sukkur': 0.1, 'pk-sindh-nawabshah': 0.1, 'pk-sindh-mirpur-khas': 0.1, 'pk-sindh-tando-allahyar': 0.09,
  'pk-sindh-kashmore': 0.08, 'pk-sindh-ghotki': 0.06, 'pk-sindh-thatta': 0.06, 'pk-sindh-umerkot': 0.03, 'pk-sindh-hyderabad': 0.02,
  'pk-sindh-tharparkar': 0.005, 'pk-sindh-karachi': 0.001,
};
export const sum = (xs) => xs.reduce((a, b) => a + b, 0);
const r1 = (n) => Math.round(n * 10) / 10;
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const districtRows = snapshot.map((s) => {
  const g = geoList.find((x) => x.id === s.district_id);
  const fraction = FLOOD_FRACTION[s.district_id] ?? 0.05;
  return {
    district_id: s.district_id,
    name: s.name,
    name_ur: g?.ur ?? s.name,
    ring: g?.ring,
    pop: s.population,
    road: s.road_access,
    alt: s.alt_delivery_fraction,
    defSev: s.default_severity,
    area: s.area_km2,
    fraction,
    flood: r1(fraction * s.area_km2),
    popAffected: Math.round(s.population * Math.min(1, fraction * 1.6)),
    sev: Number(clamp(s.default_severity * 0.5 + fraction * 1.5, 0.05, 1).toFixed(2)),
  };
});
export const nameOf = (id, lang) => {
  const d = districtRows.find((x) => x.district_id === id);
  if (!d) return id;
  return lang === 'ur' ? d.name_ur : d.name;
};

// ---------- eyes ----------
export function eyesCompare() {
  const by = districtRows.map((r) => ({ district_id: r.district_id, name: r.name, flooded_km2: r.flood, flooded_fraction: Number(r.fraction.toFixed(4)), district_area_km2: r.area }));
  const newFlood = r1(sum(by.map((b) => b.flooded_km2)));
  const perm = 2073.8;
  return { total_water_km2: r1(newFlood + perm), permanent_water_km2: perm, new_flood_km2: newFlood, by_district: by };
}
export function eyesSegment() {
  const cmp = eyesCompare();
  const features = districtRows.filter((r) => r.fraction >= 0.09).map((r, i) => ({
    type: 'Feature',
    properties: { district_id: r.district_id, kind: 'flood' },
    geometry: blobOf(r.ring, Math.min(0.8, 0.3 + r.fraction * 1.1), i),
  }));
  const ref = districtRows.filter((r) => r.fraction >= 0.18).map((r, i) => ({
    type: 'Feature',
    properties: { district_id: r.district_id, kind: 'reference', note: 'placeholder outline' },
    geometry: blobOf(r.ring, Math.min(0.85, 0.34 + r.fraction * 1.1), i + 3),
  }));
  return {
    flood_extent_km2: cmp.new_flood_km2,
    extent_geojson: { type: 'FeatureCollection', features },
    permanent_water_km2: cmp.permanent_water_km2,
    confidence: 0.87,
    tiles_processed: 96,
    source_scene: { sensor: 'Sentinel-1A IW GRDH (VV+VH)', acquired: '2022-08-30T01:07:12Z', scene_id: 'S1A_IW_GRDH_1SDV_20220830T010712_DEMO' },
    validation: {
      validated_for_region: false,
      eval_dataset: 'sen1floods11_test',
      note: 'The model is validated on the Sen1Floods11 test split only. This Sindh scene is a demo scene and is not validated.',
    },
    reference_overlay_geojson: { type: 'FeatureCollection', features: ref },
    reference_overlay_note: 'Placeholder outline standing in for a UNOSAT/CEMS reference extent. Qualitative only.',
    valid_fraction: 0.97,
    model_variant: 'unet-resnet18-s1-int8',
  };
}
// ---------- oracle ----------
const erf = (x) => {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
};
export const THRESHOLD = 17500;
export function oracleForecast() {
  const p50 = [16800, 17350, 17900, 18100, 17700, 17000, 16100];
  const forecast = p50.map((m, i) => {
    const spread = m * (0.045 + 0.012 * i);
    const date = new Date(Date.parse('2022-08-31') + i * 86400000).toISOString().slice(0, 10);
    return { date, lead_days: i + 1, discharge: { p10: Math.round(m - spread), p50: m, p90: Math.round(m + spread * 1.1) } };
  });
  const exceedance_prob = forecast.map((f) => {
    const sigma = (f.discharge.p90 - f.discharge.p10) / 2.563;
    const z = (THRESHOLD - f.discharge.p50) / sigma;
    return { date: f.date, p_exceed: Number((0.5 * (1 - erf(z / Math.SQRT2))).toFixed(3)) };
  });
  return {
    station_id: 'indus-sukkur',
    unit: 'm3/s',
    as_of: '2022-08-30',
    target_kind: 'modeled_glofas',
    target_label: 'Modeled river discharge (GloFAS via Open-Meteo)',
    forecast,
    danger_threshold_m3s: THRESHOLD,
    exceedance_prob,
    calibration: { method: 'split_conformal', nominal_coverage: 0.8, n_calibration: 180 },
    station: { name: 'Sukkur barrage', river: 'Indus', requested_lat: 27.7, requested_lon: 68.85, cell_lat: 27.75, cell_lon: 68.85 },
  };
}
export const oracleExplain = () => ({
  drivers: [
    { feature: 'upstream rainfall, last 5 days', contribution_m3s: 1450, direction: 'up' },
    { feature: 'antecedent discharge', contribution_m3s: 820, direction: 'up' },
    { feature: 'seasonal baseline', contribution_m3s: -410, direction: 'down' },
  ],
  narrative: 'Modeled discharge is above its seasonal baseline mainly because of upstream rainfall over the last five days and already high discharge.',
  baseline_m3s: 15100,
});

// ---------- library ----------
const SRC = (n) => ({ doc_id: `demo-excerpt-${n}`, publisher: 'Demo fixture (excerpt authored for UI development)', url: null, lang: 'en' });
export const guidance = {
  water: {
    query: 'How much drinking water does one person need per day in an emergency?',
    answer: 'Plan for at least 15 litres of water per person per day for drinking, cooking and hygiene.',
    citation: { ...SRC('water'), title: 'Demo excerpt: water supply guidance', page: 3, span: [120, 245], quote: 'Average water use for drinking, cooking and personal hygiene in any household is at least 15 litres per person per day.' },
    claim: 'Plan for at least 15 litres of water per person per day for drinking, cooking and hygiene.',
    claim_ur: 'پینے، کھانا پکانے اور صفائی کے لیے فی شخص روزانہ کم از کم 15 لیٹر پانی کا بندوبست کریں۔',
    quantities: [{ value: 15, unit: 'litre', per: 'person_day', claim_idx: 0 }],
  },
  food: {
    query: 'What food energy should emergency rations provide?',
    answer: 'Rations should supply about 2,100 kilocalories per person per day.',
    citation: { ...SRC('food'), title: 'Demo excerpt: food assistance guidance', page: 7, span: [40, 160], quote: 'The initial planning figure for the energy requirement of a population is 2,100 kilocalories per person per day.' },
    claim: 'Rations should supply about 2,100 kilocalories per person per day.',
    claim_ur: 'راشن سے فی شخص روزانہ تقریباً 2,100 کلو کیلوری توانائی ملنی چاہیے۔',
    quantities: [{ value: 2100, unit: 'kcal', per: 'person_day', claim_idx: 0 }],
  },
  shelter: {
    query: 'What covered space should each displaced person have?',
    answer: 'Provide at least 3.5 square metres of covered living space per person.',
    citation: { ...SRC('shelter'), title: 'Demo excerpt: shelter and settlement guidance', page: 12, span: [210, 330], quote: 'People have at least 3.5 square metres of covered living space per person.' },
    claim: 'Provide at least 3.5 square metres of covered living space per person.',
    claim_ur: 'ہر شخص کے لیے کم از کم 3.5 مربع میٹر ڈھکی ہوئی رہائشی جگہ فراہم کریں۔',
    quantities: [{ value: 3.5, unit: 'm2', per: 'person', claim_idx: 0 }],
  },
};
export function libraryAnswer(key, { refuse = false, lang = 'en' } = {}) {
  const g = guidance[key];
  if (refuse) {
    return {
      status: 'refused',
      answer: null,
      citations: [],
      claims: [],
      refusal: { reason: 'INSUFFICIENT_EVIDENCE', closest_hits: [g.citation] },
      quantities: [],
    };
  }
  const citation = lang === 'ur' ? { ...g.citation, lang: 'en' } : g.citation;
  return {
    status: 'answered',
    answer: lang === 'ur' ? g.claim_ur : g.answer,
    citations: [citation],
    claims: [{ text: lang === 'ur' ? g.claim_ur : g.claim, citation_idx: [0] }],
    refusal: null,
    quantities: g.quantities,
    generation: { mode: 'extractive', model: null, provider: null },
  };
}
export const askAnswers = {
  answered: { question: 'How much water per person per day?', key: 'water' },
  refused: { question: 'Which bridges will collapse tomorrow?' },
};

// ---------- ledger ----------
export const COMMODITIES = [
  { id: 'water', name: 'Drinking water', name_ur: 'پینے کا پانی', unit: 'litre', unit_cost: 0.03, per_person_need: 70 },
  { id: 'food', name: 'Food ration', name_ur: 'خوراک کا راشن', unit: 'ration', unit_cost: 4.5, per_person_need: 7 },
  { id: 'shelter', name: 'Shelter kit', name_ur: 'پناہ گاہ کٹ', unit: 'kit', unit_cost: 38, per_person_need: 0.2 },
];
export const SUPPLY = { water: 300_000_000, food: 30_000_000, shelter: 700_000 };
export const BUDGET = 120_000_000;
export const MIN_ROAD_ACCESS = 0.25;

export function ledgerDistricts() {
  return districtRows.map((r) => ({ district_id: r.district_id, name: r.name, population: r.pop, road_access: r.road, alt_delivery_fraction: r.alt, default_severity: r.defSev }));
}
export function ledgerOptimize() {
  const accessOf = (r) => (r.road >= MIN_ROAD_ACCESS ? 'road' : r.alt > 0 ? 'air_boat' : 'unreachable');
  const weight = (r) => (accessOf(r) === 'unreachable' ? 0 : r.popAffected * r.sev * (accessOf(r) === 'road' ? 0.4 + 0.6 * r.road : r.alt));
  const wsum = sum(districtRows.map(weight));
  const rawCost = sum(COMMODITIES.map((c) => SUPPLY[c.id] * c.unit_cost));
  const scale = Math.min(1, BUDGET / rawCost);
  const allocation = [];
  const covMin = {};
  for (const c of COMMODITIES) {
    for (const r of districtRows) {
      const qty = Math.floor((SUPPLY[c.id] * scale * weight(r)) / wsum);
      allocation.push({ district_id: r.district_id, commodity_id: c.id, quantity: qty });
      const need = r.popAffected * c.per_person_need;
      covMin[r.district_id] = Math.min(covMin[r.district_id] ?? 1, need > 0 ? qty / need : 1);
    }
  }
  const coverage = districtRows.map((r) => {
    const mode = accessOf(r);
    const frac = mode === 'unreachable' ? 0 : Number(Math.min(1, covMin[r.district_id] ?? 0).toFixed(3));
    return { district_id: r.district_id, fraction: frac, access_mode: mode, unreached_people: mode === 'unreachable' ? r.popAffected : Math.round(r.popAffected * (1 - frac)) > 0 && mode === 'air_boat' ? Math.round(r.popAffected * (1 - r.alt)) : 0 };
  });
  const peopleCovered = Math.round(sum(districtRows.map((r, i) => r.popAffected * coverage[i].fraction)));
  const totalCost = Math.round(sum(allocation.map((a) => a.quantity * COMMODITIES.find((c) => c.id === a.commodity_id).unit_cost)));
  return {
    status: 'optimal',
    allocation,
    coverage,
    equity: { floor_requested: 0.4, floor_applied: 0.4, max_feasible_floor: 0.72 },
    total_coverage: Math.round(sum(districtRows.map((r, i) => r.popAffected * r.sev * coverage[i].fraction))),
    total_cost: totalCost,
    optimality_gap: 0,
    cost_benefit: { cost_per_person_covered: Number((totalCost / Math.max(1, peopleCovered)).toFixed(2)), people_covered: peopleCovered },
    solver: { name: 'GLOP', version: '9.x (fixture)', wall_time_s: 0.42 },
  };
}export function ledgerSensitivity(opt) {
  const base = opt.total_coverage;
  const tradeoff = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((f) => {
    if (f > 0.72) return { min_coverage_floor: f, status: 'infeasible', total_coverage: null, people_covered: null };
    const cov = Math.round(base * (1.05 - 0.22 * f * f - 0.06 * f));
    return { min_coverage_floor: f, status: f >= 0.7 ? 'feasible' : 'optimal', total_coverage: cov, people_covered: Math.round(opt.cost_benefit.people_covered * (1.04 - 0.2 * f * f - 0.05 * f)) };
  });
  const at0 = tradeoff[0].total_coverage;
  const atFloor = tradeoff.find((t) => t.min_coverage_floor === opt.equity.floor_applied)?.total_coverage ?? base;
  return {
    shadow_prices: [
      { constraint: 'supply:water', value: 0.0031, unit: 'weighted people covered per litre', binding: true },
      { constraint: 'supply:food', value: 0.41, unit: 'weighted people covered per ration', binding: true },
      { constraint: 'supply:shelter', value: 0, unit: 'weighted people covered per kit', binding: false },
      { constraint: 'budget', value: 0.000052, unit: 'weighted people covered per currency unit', binding: true },
      { constraint: 'equity_floor', value: -0.0021, unit: 'weighted people covered per floor point', binding: true },
    ],
    reduced_costs: [{ district_id: 'pk-sindh-hyderabad', commodity_id: 'food', value: -0.12 }],
    ranges: [{ constraint: 'supply:water', allowable_increase: 12_000_000, allowable_decrease: 31_000_000 }],
    basis: 'lp_relaxation',
    equity_tradeoff: tradeoff,
    equity_cost: at0 - atFloor,
    notes: ['Shadow prices come from the LP relaxation; the plan itself uses integer quantities.'],
  };
}