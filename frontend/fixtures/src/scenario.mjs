// Builds one scenario: the SSE event list, the evidence documents and the Briefing.
import {
  BUDGET, COMMODITIES, SUPPLY, T0, THRESHOLD, districtRows, eyesCompare, eyesSegment, iso, ledgerDistricts, ledgerOptimize, ledgerSensitivity,
  libraryAnswer, nameOf, oracleExplain, oracleForecast, sum, toolResult, uid, FIXTURE_SOURCE, CONTRACT_VERSION, guidance,
} from './data.mjs';

const fmt = (n, d = 0) => Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const UNIT_UR = { litre: 'لیٹر', ration: 'راشن', kit: 'کٹ' };

export const SCENARIOS = ['default-demo', 'conflict', 'organ-error', 'refusal', 'partial', 'offline-fallback'];

const NODES = [
  { id: 'eyes.segment', organ: 'eyes', tool: 'segment_flood', kind: 'organ', from: 300, to: 2600, timeout: 30 },
  { id: 'eyes.compare', organ: 'eyes', tool: 'compare_with_permanent_water', kind: 'organ', from: 300, to: 1900, timeout: 30 },
  { id: 'oracle.forecast', organ: 'oracle', tool: 'forecast_river', kind: 'organ', from: 300, to: 1500, timeout: 8 },
  { id: 'oracle.explain', organ: 'oracle', tool: 'explain_forecast', kind: 'organ', from: 1600, to: 2200, timeout: 8, optional: true, deps: ['oracle.forecast'] },
  { id: 'library.water', organ: 'library', tool: 'answer_with_citations', kind: 'organ', from: 300, to: 1700, timeout: 20 },
  { id: 'library.food', organ: 'library', tool: 'answer_with_citations', kind: 'organ', from: 400, to: 1900, timeout: 20 },
  { id: 'library.shelter', organ: 'library', tool: 'answer_with_citations', kind: 'organ', from: 500, to: 2100, timeout: 20 },
  { id: 'ledger.districts', organ: 'ledger', tool: 'resource:ledger.districts', kind: 'resource', from: 300, to: 700, timeout: 5 },
  { id: 'ledger.optimize', organ: 'ledger', tool: 'optimize_allocation', kind: 'organ', from: 3000, to: 4400, timeout: 15, deps: ['derive.ledger_input'] },
  { id: 'ledger.sensitivity', organ: 'ledger', tool: 'sensitivity_report', kind: 'organ', from: 4500, to: 5400, timeout: 15, optional: true, deps: ['ledger.optimize'] },
];

export function buildScenario({ name = 'default-demo', lang = 'en' } = {}) {
  const oracleFail = name === 'organ-error';
  const refusal = name === 'refusal';
  const partial = name === 'partial';
  const offline = name === 'offline-fallback';
  // Brain decision 20.8: the headline scenario is conflict-free; the seeded conflict lives in its own scenario.
  const hasConflict = name === 'conflict';
  const scenarioId = hasConflict ? 'demo-sindh-2022-conflicts' : 'demo-sindh-2022';
  const L = (en, ur) => (lang === 'ur' ? ur : en);

  // ----- tool results -----
  const res = {};
  res['eyes.segment'] = toolResult('eyes', 'segment_flood', eyesSegment(), { at: 2600, sources: [FIXTURE_SOURCE, { id: 'sentinel-1-demo', name: 'Sentinel-1 scene, Sindh Aug 2022 (clipped, demo)', license: 'Copernicus Sentinel data terms', as_of: '2022-08-30' }] });
  res['eyes.compare'] = toolResult('eyes', 'compare_with_permanent_water', eyesCompare(), { at: 1900 });
  res['oracle.forecast'] = oracleFail
    ? toolResult('oracle', 'forecast_river', null, { ok: false, error: { code: 'TIMEOUT', message: 'Oracle did not answer within 8 s', retryable: true }, at: 8300 })
    : toolResult('oracle', 'forecast_river', oracleForecast(), { at: 1500, sources: [FIXTURE_SOURCE, { id: 'open-meteo-glofas', name: 'GloFAS discharge via Open-Meteo flood API (modeled)', license: 'CC BY 4.0', as_of: '2022-08-30' }] });
  if (!oracleFail) res['oracle.explain'] = toolResult('oracle', 'explain_forecast', oracleExplain(), { at: 2200 });
  for (const q of ['water', 'food', 'shelter']) {
    res[`library.${q}`] = toolResult('library', 'answer_with_citations', libraryAnswer(q, { refuse: refusal && q === 'shelter', lang }), { at: 1700, runName: `library.${q}`, mode: 'demo' });
  }
  res['ledger.districts'] = toolResult('ledger', 'resource:ledger.districts', ledgerDistricts(), { at: 700 });
  const opt = ledgerOptimize();
  res['ledger.optimize'] = toolResult('ledger', 'optimize_allocation', opt, { at: 4400 });
  if (!partial) res['ledger.sensitivity'] = toolResult('ledger', 'sensitivity_report', ledgerSensitivity(opt), { at: 5400 });

  // Brain-origin evidence (not a schema-validated ToolResult)
  const assumptions = [
    L('Water need is assumed to be 10 litres per person per day (70 litres per person for the 7-day period).', 'پانی کی ضرورت فی شخص روزانہ 10 لیٹر فرض کی گئی ہے (7 دن کے لیے فی شخص 70 لیٹر)۔'),
    L('Severity per district is mapped from the flooded fraction reported by Eyes.', 'ہر ضلع کی شدت آئیز کی رپورٹ کردہ سیلابی نسبت سے لی گئی ہے۔'),
    oracleFail ? L('The river forecast was not available, so the river-risk term is zero.', 'دریا کی پیش گوئی دستیاب نہیں تھی، اس لیے دریائی خطرے کا جزو صفر ہے۔') : L('The river-risk term uses the modeled peak exceedance probability.', 'دریائی خطرے کا جزو ماڈل شدہ بلند ترین سطح سے تجاوز کے امکان پر مبنی ہے۔'),
  ];
  const brainEntries = {
    derive: { run_id: uid('brain.derive.ledger_input'), organ: 'brain', tool: 'derive.ledger_input', data: { assumptions, water_l_per_person_day: 10, commodities: COMMODITIES, supply: SUPPLY, budget: BUDGET }, mode: 'demo' },
    disclaimer: { run_id: uid('brain.static.disclaimer'), organ: 'brain', tool: 'static.disclaimer', data: { text: L('Stitch is decision support, not an operational authority. Verify with local responders.', 'اسٹِچ فیصلہ سازی میں معاون ہے، آپریشنل اتھارٹی نہیں۔ مقامی امدادی اداروں سے تصدیق کریں۔') }, mode: 'demo' },
  };

  const ev = (key, organ, tool, pointer) => ({ run_id: res[key].provenance.run_id, organ, tool, json_pointer: pointer });
  const brainRef = (e, pointer) => ({ run_id: e.run_id, organ: 'brain', tool: e.tool, json_pointer: pointer });
  const E = {
    seg: (p) => ev('eyes.segment', 'eyes', 'segment_flood', p),
    cmp: (p) => ev('eyes.compare', 'eyes', 'compare_with_permanent_water', p),
    fc: (p) => ev('oracle.forecast', 'oracle', 'forecast_river', p),
    lib: (q, p) => ev(`library.${q}`, 'library', 'answer_with_citations', p),
    opt: (p) => ev('ledger.optimize', 'ledger', 'optimize_allocation', p),
    sens: (p) => ev('ledger.sensitivity', 'ledger', 'sensitivity_report', p),
  };

  // ----- claims -----
  const cmp = res['eyes.compare'].data;
  const seg = res['eyes.segment'].data;
  const claims = { extent: [], forecast: [], guidance: [], allocation: [], caveats: [] };
  claims.extent.push({
    id: 'extent.flood_area', kind: 'number',
    text: L(`New flood water covers ${fmt(cmp.new_flood_km2, 1)} km2 (${fmt(cmp.total_water_km2, 1)} km2 total water, ${fmt(cmp.permanent_water_km2, 1)} km2 permanent) in the scene acquired 2022-08-30.`,
      `نئے سیلابی پانی نے ${fmt(cmp.new_flood_km2, 1)} مربع کلومیٹر رقبہ ڈھانپ لیا ہے (کل پانی ${fmt(cmp.total_water_km2, 1)} مربع کلومیٹر، مستقل پانی ${fmt(cmp.permanent_water_km2, 1)} مربع کلومیٹر)، منظر 2022-08-30 کا ہے۔`),
    evidence: [E.cmp('/data/new_flood_km2'), E.cmp('/data/total_water_km2'), E.cmp('/data/permanent_water_km2'), E.seg('/data/source_scene/acquired')],
  });
  const top = [...cmp.by_district].map((d, i) => ({ ...d, i })).sort((a, b) => b.flooded_km2 - a.flooded_km2 || a.district_id.localeCompare(b.district_id)).slice(0, 3);
  claims.extent.push({
    id: 'extent.top_districts', kind: 'number',
    text: L(`Largest flooded areas: ${top.map((d) => `${nameOf(d.district_id, 'en')} ${fmt(d.flooded_km2, 1)} km2 (${fmt(d.flooded_fraction * 100, 1)}% of the district)`).join(', ')}.`,
      `سب سے زیادہ متاثرہ علاقے: ${top.map((d) => `${nameOf(d.district_id, 'ur')} ${fmt(d.flooded_km2, 1)} مربع کلومیٹر (ضلع کا ${fmt(d.flooded_fraction * 100, 1)}%)`).join('، ')}۔`),
    evidence: top.flatMap((d) => [E.cmp(`/data/by_district/${d.i}/flooded_km2`), E.cmp(`/data/by_district/${d.i}/flooded_fraction`)]),
  });
  claims.extent.push({
    id: 'extent.confidence', kind: 'number',
    text: L(`Mean segmentation confidence over flood pixels: ${seg.confidence}.`, `سیلابی پکسلز پر اوسط درجہ بندی اعتماد: ${seg.confidence}۔`),
    evidence: [E.seg('/data/confidence')],
  });

  if (!oracleFail) {
    const fc = res['oracle.forecast'].data;
    const pk = fc.forecast.reduce((b, f, i) => (f.discharge.p50 > fc.forecast[b].discharge.p50 ? i : b), 0);
    const ex = fc.exceedance_prob.reduce((b, f, i) => (f.p_exceed > fc.exceedance_prob[b].p_exceed ? i : b), 0);
    claims.forecast.push({
      id: 'forecast.peak', kind: 'number', labels: ['modeled'],
      text: L(`Modeled river discharge (GloFAS via Open-Meteo) near ${fc.station.name}: peak median ${fmt(fc.forecast[pk].discharge.p50)} m3/s on ${fc.forecast[pk].date} (p10 ${fmt(fc.forecast[pk].discharge.p10)}, p90 ${fmt(fc.forecast[pk].discharge.p90)} m3/s).`,
        `ماڈل شدہ دریائی بہاؤ (GloFAS بذریعہ Open-Meteo) سکھر کے قریب: درمیانی بلند ترین سطح ${fmt(fc.forecast[pk].discharge.p50)} m3/s بتاریخ ${fc.forecast[pk].date} (p10 ${fmt(fc.forecast[pk].discharge.p10)}، p90 ${fmt(fc.forecast[pk].discharge.p90)} m3/s)۔`),
      evidence: [E.fc(`/data/forecast/${pk}/discharge/p50`), E.fc(`/data/forecast/${pk}/discharge/p10`), E.fc(`/data/forecast/${pk}/discharge/p90`), E.fc(`/data/forecast/${pk}/date`)],
    });
    claims.forecast.push({
      id: 'forecast.exceedance', kind: 'number', labels: ['modeled'],
      text: L(`Modeled probability of exceeding ${fmt(THRESHOLD)} m3/s peaks at ${fmt(fc.exceedance_prob[ex].p_exceed * 100)}% on ${fc.exceedance_prob[ex].date}.`,
        `ماڈل کے مطابق ${fmt(THRESHOLD)} m3/s سے تجاوز کا امکان ${fc.exceedance_prob[ex].date} کو ${fmt(fc.exceedance_prob[ex].p_exceed * 100)}% کی بلند ترین سطح پر ہے۔`),
      evidence: [E.fc(`/data/exceedance_prob/${ex}/p_exceed`), E.fc('/data/danger_threshold_m3s')],
    });
    claims.forecast.push({
      id: 'forecast.calibration', kind: 'statement', labels: ['modeled'],
      text: L(`Modeled intervals are ${fmt(fc.calibration.nominal_coverage * 100)}% split-conformal bands from ${fc.calibration.n_calibration} calibration points.`,
        `ماڈل شدہ وقفے ${fc.calibration.n_calibration} کیلیبریشن نقاط سے بنے ${fmt(fc.calibration.nominal_coverage * 100)}% اسپلٹ کنفارمل بینڈ ہیں۔`),
      evidence: [E.fc('/data/calibration/nominal_coverage'), E.fc('/data/calibration/n_calibration')],
    });
    claims.forecast.push({
      id: 'forecast.drivers', kind: 'statement', labels: ['modeled'],
      text: res['oracle.explain'].data.narrative,
      evidence: [ev('oracle.explain', 'oracle', 'explain_forecast', '/data/narrative')],
    });
  }

  for (const q of ['water', 'food', 'shelter']) {
    const r = res[`library.${q}`].data;
    if (r.status === 'answered') {
      claims.guidance.push({
        id: `guidance.${q}.0`, kind: 'statement',
        text: r.claims[0].text,
        evidence: [E.lib(q, '/data/claims/0/text'), E.lib(q, '/data/citations/0')],
      });
    } else {
      claims.guidance.push({
        id: `guidance.${q}.refusal`, kind: 'statement', labels: ['refusal'],
        text: L(`The guidance library declined to answer "${guidance[q].query}": no sufficiently supported passage was found. No guidance is given from memory.`,
          `رہنمائی کی لائبریری نے سوال کا جواب دینے سے انکار کیا: مناسب شواہد پر مبنی کوئی عبارت نہیں ملی۔ یادداشت سے کوئی رہنمائی نہیں دی جاتی۔`),
        evidence: [E.lib(q, '/data/refusal/reason'), E.lib(q, '/data/refusal/closest_hits/0')],
      });
    }
  }

  const alloc = res['ledger.optimize'].data;
  claims.allocation.push({
    id: 'allocation.summary', kind: 'number',
    text: L(`The plan covers ${fmt(alloc.cost_benefit.people_covered)} people at ${fmt(alloc.cost_benefit.cost_per_person_covered, 2)} per person (${fmt(alloc.total_cost)} total); solver status: ${alloc.status}.`,
      `منصوبہ ${fmt(alloc.cost_benefit.people_covered)} افراد کو فی کس ${fmt(alloc.cost_benefit.cost_per_person_covered, 2)} کی لاگت پر احاطہ کرتا ہے (کل ${fmt(alloc.total_cost)})؛ سولور کی حالت: ${alloc.status}۔`),
    evidence: [E.opt('/data/cost_benefit/people_covered'), E.opt('/data/cost_benefit/cost_per_person_covered'), E.opt('/data/total_cost'), E.opt('/data/status')],
  });
  for (const c of COMMODITIES) {
    const rows = alloc.allocation.map((a, i) => ({ ...a, i })).filter((a) => a.commodity_id === c.id).sort((a, b) => b.quantity - a.quantity || a.district_id.localeCompare(b.district_id)).slice(0, c.id === 'water' ? 3 : 1);
    for (const r of rows) {
      claims.allocation.push({
        id: `allocation.${c.id}.${r.district_id.replace('pk-sindh-', '')}`, kind: 'recommendation', labels: hasConflict && c.id === 'water' ? ['disputed'] : undefined,
        text: L(`Send ${fmt(r.quantity)} ${c.unit}s of ${c.name.toLowerCase()} to ${nameOf(r.district_id, 'en')}.${hasConflict && c.id === 'water' ? ' (disputed, see conflict C1)' : ''}`,
          `${nameOf(r.district_id, 'ur')} کو ${fmt(r.quantity)} ${UNIT_UR[c.unit]} ${c.name_ur} بھیجیں۔${hasConflict && c.id === 'water' ? ' (متنازع، تصادم C1 دیکھیں)' : ''}`),
        evidence: [E.opt(`/data/allocation/${r.i}/quantity`)],
      });
    }
  }
  const unreached = alloc.coverage.map((c, i) => ({ ...c, i })).filter((c) => c.unreached_people > 0);
  if (unreached.length) {
    claims.allocation.push({
      id: 'allocation.unreached', kind: 'number',
      text: L(`${fmt(sum(unreached.map((u) => u.unreached_people)))} people in ${unreached.length} district cannot be reached by road, air or boat with the given inputs.`,
        `${unreached.length} ضلع میں ${fmt(sum(unreached.map((u) => u.unreached_people)))} افراد تک دی گئی معلومات کے مطابق سڑک، ہوائی یا کشتی کے ذریعے رسائی ممکن نہیں۔`),
      evidence: unreached.map((u) => E.opt(`/data/coverage/${u.i}/unreached_people`)),
    });
  }
  if (!partial) {
    const s = res['ledger.sensitivity'].data;
    claims.allocation.push({
      id: 'allocation.equity', kind: 'statement',
      text: L(`Equity floor requested ${alloc.equity.floor_requested}, applied ${alloc.equity.floor_applied} (highest feasible ${alloc.equity.max_feasible_floor}); coverage given up for equity: ${fmt(s.equity_cost)}.`,
        `مساوات کی حد ${alloc.equity.floor_requested} مانگی گئی، ${alloc.equity.floor_applied} لاگو ہوئی (زیادہ سے زیادہ ممکن ${alloc.equity.max_feasible_floor})؛ مساوات کے لیے چھوڑا گیا احاطہ: ${fmt(s.equity_cost)}۔`),
      evidence: [E.opt('/data/equity/floor_applied'), E.sens('/data/equity_cost')],
    });
    claims.allocation.push({
      id: 'allocation.shadow.water', kind: 'number',
      text: L(`One more litre of water would raise weighted coverage by about ${s.shadow_prices[0].value} (${s.shadow_prices[0].unit}).`, `ایک لیٹر مزید پانی وزنی احاطے میں ${s.shadow_prices[0].value} کا اضافہ کرے گا۔`),
      evidence: [E.sens('/data/shadow_prices/0/value')],
    });
  }

  const conflict = {
    id: 'C1', rule_id: 'R3', status: 'final', subjects: ['water'], organs: ['library', 'ledger'], resolution: 'flagged',
    description: L('The Library recommends 15 litres of water per person per day, but the allocation plan assumes 10 litres per person per day.',
      'لائبریری فی شخص روزانہ 15 لیٹر پانی تجویز کرتی ہے، لیکن تقسیم کے منصوبے میں فی شخص روزانہ 10 لیٹر فرض کیا گیا ہے۔'),
    evidence: [E.lib('water', '/data/claims/0/text'), brainRef(brainEntries.derive, '/data/water_l_per_person_day')],
  };

  claims.caveats.push({ id: 'caveat.disclaimer', kind: 'statement', text: brainEntries.disclaimer.data.text, evidence: [brainRef(brainEntries.disclaimer, '/data/text')] });
  claims.caveats.push({
    id: 'caveat.mode', kind: 'statement', labels: ['demo'],
    text: L('Demo mode: figures come from committed demo data, not live feeds.', 'ڈیمو موڈ: اعداد و شمار محفوظ شدہ ڈیمو ڈیٹا سے ہیں، براہ راست ذرائع سے نہیں۔'),
    evidence: [E.seg('/provenance/mode')],
  });
  claims.caveats.push({
    id: 'caveat.eyes_unvalidated', kind: 'statement', labels: ['unvalidated'],
    text: L('Demo scene: Sindh, Aug 2022. The flood-mapping model was validated on sen1floods11_test, not on this region. Treat the extent as unvalidated.',
      'ڈیمو منظر: سندھ، اگست 2022۔ سیلاب کی نقشہ سازی کا ماڈل sen1floods11_test پر جانچا گیا ہے، اس خطے پر نہیں۔ اس حد کو غیر تصدیق شدہ سمجھیں۔'),
    evidence: [E.seg('/data/validation/validated_for_region'), E.seg('/data/validation/eval_dataset')],
  });
  if (!oracleFail) {
    claims.caveats.push({
      id: 'caveat.oracle_modeled', kind: 'statement', labels: ['modeled'],
      text: L('River figures are model output (Modeled river discharge (GloFAS via Open-Meteo)), not instrument readings.', 'دریا کے اعداد ماڈل کا نتیجہ ہیں (ماڈل شدہ دریائی بہاؤ، GloFAS بذریعہ Open-Meteo)، آلات کی ریڈنگ نہیں۔'),
      evidence: [E.fc('/data/target_kind'), E.fc('/data/target_label')],
    });
  } else {
    claims.caveats.push({
      id: 'caveat.missing.oracle', kind: 'statement',
      text: L('Oracle did not answer (TIMEOUT). The forecast section is unavailable.', 'اوریکل نے جواب نہیں دیا (TIMEOUT)۔ پیش گوئی کا حصہ دستیاب نہیں۔'),
      evidence: [E.fc('/error/code')],
    });
  }
  claims.caveats.push({ id: 'caveat.assumptions', kind: 'statement', text: assumptions.join(' '), evidence: [brainRef(brainEntries.derive, '/data/assumptions')] });
  claims.caveats.push({
    id: 'caveat.conflict.C1', kind: 'statement',
    text: L(`Unresolved disagreement: ${conflict.description} Neither side is treated as settled.`, `غیر حل شدہ اختلاف: ${conflict.description} کسی فریق کو طے شدہ نہیں سمجھا گیا۔`),
    evidence: conflict.evidence,
  });
  if (offline) {
    claims.caveats.push({
      id: 'caveat.fallback', kind: 'statement', labels: ['demo'],
      text: L('Live data was requested but unavailable. This briefing uses the demo scene.', 'براہ راست ڈیٹا مانگا گیا تھا لیکن دستیاب نہیں تھا۔ یہ بریفنگ ڈیمو منظر استعمال کرتی ہے۔'),
      evidence: [E.seg('/provenance/mode')],
    });
  }

  const titles = {
    extent: L('Flood extent', 'سیلاب کی حد'), forecast: L('River forecast', 'دریا کی پیش گوئی'), guidance: L('Guidance', 'رہنمائی'),
    allocation: L('Allocation', 'امداد کی تقسیم'), caveats: L('Caveats', 'احتیاطیں'),
  };
  const status = (id) => {
    if (id === 'forecast' && oracleFail) return ['unavailable', [L('river forecast', 'دریا کی پیش گوئی')]];
    if (id === 'allocation' && partial) return ['partial', [L('sensitivity report (shadow prices and equity trade-off)', 'حساسیت رپورٹ (شیڈو قیمتیں اور مساوات کا توازن)')]];
    return ['ok', undefined];
  };
  const sections = ['extent', 'forecast', 'guidance', 'allocation', 'caveats'].map((id) => {
    const [st, missing] = status(id);
    const s = { id, title: titles[id], status: st, claims: claims[id] };
    if (missing) s.missing = missing;
    return s;
  });
  const total = sum(Object.values(claims).map((c) => c.length));
  const briefing = {
    briefing_id: uid(`briefing.${name}.${lang}`),
    scenario: scenarioId,
    lang,
    mode: 'demo',
    sections,
    conflicts: hasConflict ? [conflict] : [],
    critic: { passed: true, removed_claims: [], notes: [L(`All ${total} claims were re-verified against stored evidence.`, `تمام ${total} دعوے محفوظ شواہد کے مقابل دوبارہ جانچے گئے۔`)] },
    confidence: oracleFail ? 0.55 : refusal ? 0.74 : partial ? 0.7 : 0.78,
    generated_at: iso(6200),
  };

  // ----- events -----
  const raw = [];
  const push = (t, event, task_id, extra, payload) => raw.push({ t, event, data: { event, ts: iso(t), task_id, ...extra, payload } });
  const live = offline ? 'live' : 'demo';
  const nodes = NODES.filter((n) => !(oracleFail && n.id === 'oracle.explain') && !(partial && n.id === 'ledger.sensitivity'));
  const planNodes = [
    ...nodes.map((n) => ({ id: n.id, kind: n.kind, organ: n.organ, tool: n.tool, deps: n.deps ?? [], optional: n.optional ?? false })),
    { id: 'derive.ledger_input', kind: 'derive', deps: ['eyes.compare', 'oracle.forecast', 'ledger.districts'], optional: false },
    { id: 'conflicts', kind: 'analysis', deps: [], optional: false },
  ];
  push(0, 'plan', 'plan', {}, { plan_id: uid(`plan.${name}`), revision: 0, planner: 'static', scenario: scenarioId, lang, mode_requested: live, nodes: planNodes, stub_organs: [] });
  if (offline) push(120, 'notice', 'run', {}, { code: 'MODE_FALLBACK', message: 'Live data is unavailable. Falling back to the demo scene.' });
  for (const n of nodes) {
    const r = res[n.id];
    const failed = !r.ok;
    const end = failed ? 8300 : n.to;
    push(n.from, 'organ_call', n.id, { organ: n.organ, tool: n.tool }, { attempt: 1, max_attempts: 1, timeout_s: n.timeout, served_by: 'real', started_at: iso(n.from) });
    const summary = {};
    if (r.ok && r.data && !Array.isArray(r.data)) for (const [k, v] of Object.entries(r.data)) if (['number', 'string', 'boolean'].includes(typeof v) && Object.keys(summary).length < 10) summary[k] = v;
    push(end, 'organ_result', n.id, { organ: n.organ, tool: n.tool }, {
      ok: r.ok, attempt: 1, duration_ms: end - n.from, served_by: 'real', run_id: r.provenance.run_id, mode: 'demo', warnings: r.warnings,
      ...(failed ? { error: r.error } : { summary }),
    });
  }
  const deriveAt = oracleFail ? 8400 : 2700;
  push(deriveAt, 'organ_call', 'derive.ledger_input', { organ: 'brain', tool: 'derive.ledger_input' }, { attempt: 1, max_attempts: 1, timeout_s: 2, served_by: 'real', started_at: iso(deriveAt) });
  push(deriveAt + 150, 'organ_result', 'derive.ledger_input', { organ: 'brain', tool: 'derive.ledger_input' }, { ok: true, attempt: 1, duration_ms: 150, served_by: 'real', run_id: brainEntries.derive.run_id, mode: 'demo' });
  // Shift ledger.optimize/sensitivity after the derive step in the oracle-fail case (derive waits for the 8 s timeout).
  const base = [...raw];
  let events = base;
  if (oracleFail) {
    events = base.map((e) => {
      if (['ledger.optimize', 'ledger.sensitivity'].includes(e.data.task_id)) {
        const shift = 8550 - 3000;
        const t = e.t + shift;
        return { ...e, t, data: { ...e.data, ts: iso(t), payload: e.data.event === 'organ_call' ? { ...e.data.payload, started_at: iso(t) } : e.data.payload } };
      }
      return e;
    });
  }
  const lastT = Math.max(...events.map((e) => e.t));
  const t1 = lastT + 100;
  const confl = { ...conflict };
  const tail = [];
  if (hasConflict) tail.push({ t: t1, event: 'conflict', data: { event: 'conflict', ts: iso(t1), task_id: 'conflicts', payload: confl } });
  tail.push({ t: t1 + 300, event: 'critic', data: { event: 'critic', ts: iso(t1 + 300), task_id: 'critic', payload: { pass: 1, passed: true, issues: [], removed: [], reverted: [] } } });
  tail.push({ t: t1 + 700, event: 'briefing', data: { event: 'briefing', ts: iso(t1 + 700), task_id: 'briefing', payload: { ...briefing, generated_at: iso(t1 + 700) } } });
  briefing.generated_at = iso(t1 + 700);
  const all = [...events, ...tail].sort((a, b) => a.t - b.t);
  let prev = 0;
  const stream = all.map((e, i) => {
    const line = { delayMs: e.t - prev, seq: i + 1, event: e.event, data: e.data };
    prev = e.t;
    return line;
  });

  // ----- evidence documents (served by /api/evidence/:run_id) -----
  const evidence = {};
  for (const [k, r] of Object.entries(res)) {
    const n = NODES.find((x) => x.id === k);
    evidence[r.provenance.run_id] = { organ: r.provenance.organ, tool: r.provenance.tool, served_by: 'real', mode: r.provenance.mode, node_id: k, generated_at: r.provenance.generated_at, doc: r };
  }
  for (const b of Object.values(brainEntries)) {
    evidence[b.run_id] = { organ: 'brain', tool: b.tool, served_by: 'brain', mode: 'demo', node_id: b.tool, generated_at: iso(2900), doc: { ok: true, data: b.data, error: null, provenance: { organ: 'brain', tool: b.tool, run_id: b.run_id, mode: 'demo', contract_version: CONTRACT_VERSION }, warnings: [] } };
  }
  return { name, lang, stream, evidence, briefing, results: res };
}

// ----- ask -----
export function buildAsk(kind, lang) {
  const refused = kind === 'refused';
  const q = refused ? 'shelter' : 'water';
  const r = libraryAnswer(q, { refuse: refused, lang });
  const res = toolResult('library', 'answer_with_citations', r, { runName: `ask.${kind}.${lang}`, at: 0 });
  const run_id = res.provenance.run_id;
  const refs = (p) => ({ run_id, organ: 'library', tool: 'answer_with_citations', json_pointer: p });
  const claim = refused
    ? { id: 'ask.refusal', kind: 'statement', labels: ['refusal'], text: lang === 'ur' ? 'لائبریری نے اس سوال کا جواب دینے سے انکار کیا: مناسب شواہد نہیں ملے۔' : 'The guidance library declined to answer: no sufficiently supported passage was found.', evidence: [refs('/data/refusal/reason')] }
    : { id: 'ask.0', kind: 'statement', text: r.claims[0].text, evidence: [refs('/data/claims/0/text'), refs('/data/citations/0')] };
  const body = { ask_id: uid(`ask.${kind}.${lang}`), status: refused ? 'refused' : 'answered', claims: refused ? [] : [claim], refusal_claim: refused ? claim : null, mode: 'demo', library_run_id: run_id, result: res };
  return { body, evidence: { [run_id]: { organ: 'library', tool: 'answer_with_citations', served_by: 'real', mode: 'demo', node_id: 'ask', generated_at: iso(0), doc: res } } };
}

// ----- organs -----
export function organList({ voice = 'ready', live = true, unwellOrgan } = {}) {
  const base = (organ, extra = {}) => ({ organ, status: 'ready', compat: 'compatible', served_by: 'real', stub: false, version: '0.1.0', ...extra });
  return {
    organs: [
      base('eyes', unwellOrgan === 'eyes' ? { status: 'unwell', reason: 'not connected' } : {}),
      base('oracle', unwellOrgan === 'oracle' ? { status: 'unwell', reason: 'not connected' } : {}),
      base('library'),
      base('ledger'),
      base('voice', voice === 'disabled' ? { status: 'disabled', reason: 'Voice is not enabled in this deployment' } : { meta: { tts_provider: 'azure', hosted: true, capabilities: ['speak', 'transcribe'] } }),
    ],
    brain_version: '0.1.0',
    contract_version: CONTRACT_VERSION,
    default_mode: 'demo',
    live_available: live,
    llm_provider: 'fake',
    build_sha: 'fixture0',
  };
}

// ----- evals -----
export function evals(kind = 'full') {
  const ts = '2026-11-20T09:30:00Z';
  const m = (id, label, value, target, direction, dataset, unit = '') => ({ id, label, value, target, unit, direction, dataset, mode: 'demo', timestamp: ts, git_sha: 'fixture0', seed: 7, notes: '' });
  if (kind === 'empty') return { generated_at: ts, git_sha: 'fixture0', organs: { eyes: { status: 'not_run' }, oracle: { status: 'not_run' }, library: { status: 'not_run' }, ledger: { status: 'not_run' }, brain: { status: 'not_run' } } };
  const organs = {
    eyes: { status: 'pass', metrics: [m('eyes.iou', 'IoU (Sen1Floods11 test)', 0.71, 0.65, 'higher', 'sen1floods11_test'), m('eyes.f1', 'F1 (Sen1Floods11 test)', 0.82, 0.78, 'higher', 'sen1floods11_test')] },
    oracle: { status: 'pass', metrics: [m('oracle.crps', 'CRPS (modeled GloFAS)', 412.5, 500, 'lower', 'glofas_sukkur_2019_2022', 'm3/s'), m('oracle.coverage', 'Interval coverage (80% nominal, modeled GloFAS)', 0.79, 0.75, 'higher', 'glofas_sukkur_2019_2022')] },
    library: { status: 'pass', metrics: [m('library.citation_accuracy', 'Citation accuracy', 0.93, 0.9, 'higher', 'qa50_test'), m('library.refusal_rate', 'Refusal rate on unanswerable questions', 0.88, 0.8, 'higher', 'qa50_test')] },
    ledger: { status: 'pass', metrics: [m('ledger.feasibility', 'Feasibility rate', 1, 0.99, 'higher', 'ledger_scenarios'), m('ledger.gap', 'Optimality gap', 0.004, 0.01, 'lower', 'ledger_scenarios')] },
    brain: { status: 'fail', metrics: [m('brain.faithfulness', 'End-to-end faithfulness', 0.94, 0.97, 'higher', 'brain_seeded')] },
  };
  if (kind === 'partial') { organs.eyes = { status: 'not_run' }; organs.brain = { status: 'not_run' }; }
  return { generated_at: kind === 'stale' ? '2026-10-01T09:30:00Z' : ts, git_sha: 'fixture0', organs };
}