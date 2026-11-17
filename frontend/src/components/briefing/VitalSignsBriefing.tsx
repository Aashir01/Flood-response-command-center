'use client';
import { m } from 'motion/react';
import dynamic from 'next/dynamic';
import type { ReactNode } from 'react';
import type { AnswerOut, Claim, Lang, OrganId, Section } from '@/api/types';
import { IconBook, IconInfo, IconPulse, IconScale, IconWarning, IconWave } from '@/components/icons';
import { Panel, Skeleton, type PanelState } from '@/components/shell/Panel';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { getAnim } from '@/motion/registry';
import { useBench } from '@/state/BenchProvider';
import { useToolDocs, type ToolDocs } from '@/state/docs';
import { usePrefs } from '@/state/prefs';
import { organOfSection } from '@/state/selectors';
import { AllocationTable, CostBenefit, ShadowPricePanel } from './AllocationParts';
import { ClaimItem } from './ClaimItem';
import { ConfidenceHeartbeat } from './ConfidenceHeartbeat';
import { ConflictBanner } from './ConflictBanner';
import { EyesLabels } from './EyesLabels';
import { LabelChip, ModeledLabel, OracleValue } from './labels';
import { RefusalCard } from './RefusalCard';

const ForecastBandChart = dynamic(() => import('@/components/charts/ForecastBandChart').then((x) => x.ForecastBandChart), {
  ssr: false,
  loading: () => <Skeleton block lines={1} />,
});
const EquityTradeoffChart = dynamic(() => import('@/components/charts/EquityTradeoffChart').then((x) => x.EquityTradeoffChart), {
  ssr: false,
  loading: () => <Skeleton block lines={1} />,
});

const SECTION_IDS: Section['id'][] = ['extent', 'forecast', 'guidance', 'allocation', 'caveats'];
const ICONS: Record<Section['id'], ReactNode> = {
  extent: <IconWave className="panel__icon" aria-hidden="true" />,
  forecast: <IconPulse className="panel__icon" aria-hidden="true" />,
  guidance: <IconBook className="panel__icon" aria-hidden="true" />,
  allocation: <IconScale className="panel__icon" aria-hidden="true" />,
  caveats: <IconInfo className="panel__icon" aria-hidden="true" />,
};
const CARD = getAnim('card-enter');

function Pulse() {
  return (
    <svg className="vital__pulse" viewBox="0 0 96 22" aria-hidden="true" focusable="false">
      <path d="M0 11h30l4-7 5 14 4-10 3 3h50" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function ClaimList({ claims, lang }: { claims: Claim[]; lang: Lang }) {
  if (!claims.length) return null;
  return (
    <ul className="claims" style={{ marginBlockStart: 12 }}>
      {claims.map((c) => (
        <ClaimItem key={c.id} claim={c} lang={lang} />
      ))}
    </ul>
  );
}

function ExtentBody({ docs, mode }: { docs: ToolDocs; mode: 'demo' | 'live' }) {
  const { t, fmt } = useLang();
  const s = docs.segment;
  const c = docs.compare;
  return (
    <>
      <EyesLabels segment={s} mode={mode} />
      {s || c ? (
        <div className="stat-row">
          <div className="stat stat--flood">
            <span className="stat__label">{t('eyes.newFlood')}</span>
            <span className="stat__value">
              <Bdi>
                {fmt.num(c?.new_flood_km2 ?? s?.flood_extent_km2)} <small>km²</small>
              </Bdi>
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">{t('eyes.perm')}</span>
            <span className="stat__value">
              <Bdi>
                {fmt.num(c?.permanent_water_km2 ?? s?.permanent_water_km2)} <small>km²</small>
              </Bdi>
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">{t('eyes.confidence')}</span>
            <span className="stat__value">{s?.confidence === null ? <small>{t('eyes.noFlood')}</small> : fmt.num(s?.confidence, 2)}</span>
          </div>
          {typeof s?.valid_fraction === 'number' ? (
            <div className="stat">
              <span className="stat__label">{t('eyes.validFraction')}</span>
              <span className="stat__value">{fmt.pct(s.valid_fraction)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
      {s ? (
        <dl className="kv" style={{ marginBlockEnd: 4 }}>
          <dt>{t('eyes.sensor')}</dt>
          <dd>
            <Bdi>{s.source_scene.sensor}</Bdi>
          </dd>
          <dt>{t('eyes.scene')}</dt>
          <dd>
            <Bdi ltr className="mono">
              {s.source_scene.scene_id}
            </Bdi>
          </dd>
          {s.model_variant ? (
            <>
              <dt>{t('eyes.model')}</dt>
              <dd>
                <Bdi ltr className="mono">
                  {s.model_variant}
                </Bdi>
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
    </>
  );
}

function ForecastBody({ docs }: { docs: ToolDocs }) {
  const { t, fmt } = useLang();
  const f = docs.forecast;
  if (!f) return null;
  const peak = f.forecast.reduce((a, b) => (b.discharge.p50 > a.discharge.p50 ? b : a), f.forecast[0] ?? { date: '', lead_days: 0, discharge: { p10: 0, p50: 0, p90: 0 } });
  const maxEx = f.exceedance_prob.reduce((a, b) => Math.max(a, b.p_exceed), 0);
  return (
    <>
      <p className="small muted" style={{ marginBlockEnd: 8 }}>
        {t('forecast.station')}: <Bdi>{f.station ? `${f.station.name} (${f.station.river})` : f.station_id}</Bdi> · <ModeledLabel label={f.target_label} />
      </p>
      <div className="stat-row">
        <div className="stat">
          <span className="stat__label">{t('forecast.peak')}</span>
          <span className="stat__value">
            <OracleValue unit="m³/s" label={f.target_label}>
              {fmt.int(peak.discharge.p50)}
            </OracleValue>
          </span>
          <span className="small muted">
            <Bdi>{fmt.date(peak.date)}</Bdi>
          </span>
        </div>
        <div className="stat">
          <span className="stat__label">{t('forecast.threshold')}</span>
          <span className="stat__value">
            {typeof f.danger_threshold_m3s === 'number' ? (
              <OracleValue unit="m³/s" label={f.target_label}>
                {fmt.int(f.danger_threshold_m3s)}
              </OracleValue>
            ) : (
              <small>{t('forecast.noThreshold')}</small>
            )}
          </span>
        </div>
        <div className="stat">
          <span className="stat__label">{t('forecast.maxExceed')}</span>
          <span className="stat__value">
            <OracleValue label={f.target_label}>{fmt.pct(maxEx)}</OracleValue>
          </span>
        </div>
      </div>
      <ForecastBandChart forecast={f} />
      <p className="small muted" style={{ marginBlockStart: 8 }} data-oracle-value="">
        {t('forecast.calibration', { coverage: fmt.pct(f.calibration.nominal_coverage), n: fmt.int(f.calibration.n_calibration) })} <ModeledLabel />
      </p>
    </>
  );
}

function GuidanceClaims({ claims, lang, docs }: { claims: Claim[]; lang: Lang; docs: ToolDocs }) {
  const { t } = useLang();
  const byRun = new Map(docs.library.map((l) => [l.runId, l.data]));
  return (
    <ul className="claims" style={{ marginBlockStart: 4 }}>
      {claims.map((c) => {
        const runId = c.evidence.find((e) => e.organ === 'library')?.run_id;
        const doc: AnswerOut | undefined = runId ? byRun.get(runId) : undefined;
        if ((c.labels ?? []).includes('refusal')) {
          return (
            <ClaimItem
              key={c.id}
              claim={c}
              lang={lang}
              extra={
                <div style={{ flexBasis: '100%' }}>
                  <RefusalCard refusal={doc?.refusal ?? { reason: 'INSUFFICIENT_EVIDENCE' }} />
                </div>
              }
            />
          );
        }
        const cites = doc?.citations ?? [];
        return (
          <ClaimItem
            key={c.id}
            claim={c}
            lang={lang}
            extra={
              cites.length ? (
                <span className="chips" aria-label={t('guidance.sources')}>
                  {cites.map((ci) => (
                    <span className="cite" key={`${ci.doc_id}-${ci.page}`}>
                      <Bdi>
                        {ci.publisher} · {t('guidance.page', { page: ci.page })}
                      </Bdi>
                    </span>
                  ))}
                </span>
              ) : null
            }
          />
        );
      })}
    </ul>
  );
}

function AllocationBody({ docs, section }: { docs: ToolDocs; section?: Section }) {
  const { t, fmt } = useLang();
  const o = docs.optimize;
  const s = docs.sensitivity;
  if (!o) return null;
  const unreached = o.coverage.filter((c) => c.unreached_people > 0);
  const total = unreached.reduce((a, c) => a + c.unreached_people, 0);
  const noSens = !s && (section?.status === 'partial' || section?.missing?.length);
  return (
    <>
      <CostBenefit opt={o} />
      {unreached.length ? (
        <p className="state state--partial small" style={{ marginBlockEnd: 12 }}>
          <span className="state__title">
            <IconWarning />
            {t('alloc.unreachedNote', { people: fmt.int(total), n: fmt.int(unreached.length) })}
          </span>
        </p>
      ) : null}
      <AllocationTable opt={o} districts={docs.districts} />
      {s ? (
        <div style={{ display: 'grid', gap: 16, marginBlockStart: 16 }}>
          <ShadowPricePanel sens={s} />
          <EquityTradeoffChart points={s.equity_tradeoff} currentFloor={o.equity?.floor_applied} equityCost={s.equity_cost} />
        </div>
      ) : noSens ? (
        <p className="small muted" style={{ marginBlockStart: 12 }}>
          {t('alloc.noSensitivity')}
        </p>
      ) : null}
    </>
  );
}

function CaveatsBody({ mode }: { mode: 'demo' | 'live' }) {
  const { t } = useLang();
  const { state } = useBench();
  const critic = state.briefing?.critic;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {critic ? (
        <div className="state" style={{ borderStyle: 'solid' }} data-testid="critic-notes">
          <p className="state__title">
            {critic.passed ? <IconInfo /> : <IconWarning />}
            {t('caveats.critic')}: {critic.passed ? t('caveats.criticPassed') : t('caveats.criticFailed')}
          </p>
          {critic.removed_claims.length ? <p className="small">{t('caveats.removed', { n: critic.removed_claims.length })}</p> : null}
          {critic.notes.length ? (
            <ul className="small">
              {critic.notes.map((n) => (
                <li key={n} dir="auto">
                  {n}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <p className="small">
        <LabelChip label={mode} /> {mode === 'demo' ? t('caveats.demo') : t('caveats.live')}
      </p>
    </div>
  );
}

export function VitalSignsBriefing() {
  const { t, fmt, lang: uiLang } = useLang();
  const { state, start, lastRequest } = useBench();
  const { fx } = usePrefs();
  const docs = useToolDocs();
  const b = state.briefing;
  const lang: Lang = b?.lang ?? uiLang;
  const mode = b?.mode ?? lastRequest?.mode ?? 'demo';
  const running = state.run.status === 'running' || state.run.status === 'starting';
  const conflicts = b?.conflicts?.length ? b.conflicts : state.conflicts;

  const sectionState = (id: Section['id'], sec?: Section): PanelState => {
    const organ = organOfSection(id);
    const ov = organ ? state.organs[organ] : undefined;
    if (sec) return sec.status === 'unavailable' ? 'error' : sec.status === 'partial' ? 'partial' : 'success';
    if (ov?.state === 'unwell' && state.run.status !== 'idle') return 'error';
    if (running) {
      if (organ && ov?.state === 'done') return 'success';
      return 'loading';
    }
    return 'empty';
  };
  const retry = () => lastRequest && void start({ region: lastRequest.region, scenario: lastRequest.scenario, mode: lastRequest.mode ?? 'demo' }, lastRequest.lang);

  return (
    <section aria-labelledby="briefing-title" id="briefing" tabIndex={-1} style={{ display: 'grid', gap: 16 }}>
      <div className="section-title">
        <h2 id="briefing-title">{t('briefing.title')}</h2>
        <span className="rule" aria-hidden="true" />
        {b ? <LabelChip label={b.mode} /> : null}
      </div>
      {b && b.lang !== uiLang ? (
        <div className="banner" role="note">
          <IconInfo />
          <span>{t('notice.langMismatch', { briefingLang: t(`lang.${b.lang}`), uiLang: t(`lang.${uiLang}`) })}</span>
          <span className="banner__actions">
            <button
              type="button"
              className="btn btn--small"
              onClick={() => lastRequest && void start({ region: lastRequest.region, scenario: lastRequest.scenario, mode: lastRequest.mode ?? 'demo' }, uiLang)}
            >
              {t('notice.regenerate', { lang: t(`lang.${uiLang}`) })}
            </button>
          </span>
        </div>
      ) : null}
      {b ? (
        <div className="panel vital">
          <ConfidenceHeartbeat confidence={b.confidence} />
          <p className="small muted" style={{ marginBlockStart: 6 }}>
            {t('briefing.generated', { time: fmt.dateTime(b.generated_at) })}
          </p>
        </div>
      ) : (
        <p className="state small muted" role="status">
          {running ? t('briefing.running') : t('briefing.empty')}
        </p>
      )}
      <ConflictBanner conflicts={conflicts} lang={lang} />
      {SECTION_IDS.map((id, i) => {
        const sec = b?.sections.find((s) => s.id === id);
        const st = sectionState(id, sec);
        const organ: OrganId | undefined = organOfSection(id);
        const ov = organ ? state.organs[organ] : undefined;
        const missing = sec?.missing?.length ? sec.missing : [];
        const title = sec?.title && lang === uiLang ? sec.title : t(`section.${id}` as MessageKey);
        const statusChip = sec ? (
          <span className={`chip ${sec.status === 'ok' ? 'chip--validated' : sec.status === 'partial' ? 'chip--unvalidated' : 'chip--disputed'}`}>
            {sec.status === 'ok' ? null : <IconWarning />}
            {t(`section.status.${sec.status}` as MessageKey)}
          </span>
        ) : null;
        const claims = sec?.claims ?? [];
        const body =
          id === 'extent' ? (
            <>
              <ExtentBody docs={docs} mode={mode} />
              <ClaimList claims={claims} lang={lang} />
            </>
          ) : id === 'forecast' ? (
            <>
              <ForecastBody docs={docs} />
              <ClaimList claims={claims} lang={lang} />
            </>
          ) : id === 'guidance' ? (
            <GuidanceClaims claims={claims} lang={lang} docs={docs} />
          ) : id === 'allocation' ? (
            <>
              <AllocationBody docs={docs} section={sec} />
              <ClaimList claims={claims} lang={lang} />
            </>
          ) : (
            <>
              <CaveatsBody mode={mode} />
              <ClaimList claims={claims} lang={lang} />
            </>
          );
        const animate = fx === 'full' && i < 8;
        return (
          <m.div
            key={id}
            initial={animate ? { opacity: 0, y: 8 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: CARD.durationMs / 1000, delay: animate ? i * 0.04 : 0, ease: [0.22, 1, 0.36, 1] }}
          >
            <Panel
              id={`card-${id}`}
              as="article"
              className="vital"
              title={title}
              icon={ICONS[id]}
              state={st}
              headerExtra={
                <>
                  {statusChip}
                  {id === 'forecast' ? <ModeledLabel /> : null}
                  <Pulse />
                </>
              }
              loadingText={organ ? t('section.loading', { organ: t(`organ.${organ}` as MessageKey) }) : undefined}
              partialText={missing.length ? t('section.partial', { missing: missing.join(', ') }) : undefined}
              error={{
                code: ov?.lastCall?.errorCode,
                reason: ov?.lastCall?.reason ?? ov?.note,
                missing: missing.length ? missing : [t(`section.${id}` as MessageKey)],
                onRetry: lastRequest ? retry : undefined,
              }}
            >
              {body}
            </Panel>
          </m.div>
        );
      })}
    </section>
  );
}
