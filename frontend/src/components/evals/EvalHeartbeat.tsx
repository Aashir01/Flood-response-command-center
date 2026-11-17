'use client';
// The eval "heartbeat" dashboard (FRN-R9): one pulse per organ, every metric with value, target, direction,
// verdict, trend and timestamp. Oracle rows always carry "Modeled (GloFAS)".
import { useCallback, useEffect, useState } from 'react';
import { api, type EvalMetric, type EvalOrgan, type EvalsLatest } from '@/api/client';
import type { ApiError } from '@/api/types';
import { ModeledLabel } from '@/components/briefing/labels';
import { IconArrow, IconCheck, IconInfo, IconPulse, IconWarning } from '@/components/icons';
import { Skeleton } from '@/components/shell/Panel';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';

export const STALE_DAYS = 7;
const ORDER = ['eyes', 'oracle', 'library', 'ledger', 'brain', 'voice'];

export function evalsState(e: EvalsLatest | null, now: number, buildSha?: string | null): 'none' | 'stale' | 'partial' | 'full' {
  if (!e || !e.generated_at || !Object.keys(e.organs).length) return 'none';
  const organs = Object.values(e.organs);
  if (organs.every((o) => o.status === 'not_run')) return 'none';
  const age = now - Date.parse(e.generated_at);
  if (age > STALE_DAYS * 86_400_000 || (buildSha && e.git_sha && buildSha !== e.git_sha)) return 'stale';
  return organs.some((o) => o.status === 'not_run' || o.status === 'error') ? 'partial' : 'full';
}

export function metricPasses(m: EvalMetric): boolean | null {
  if (m.target === null || m.target === undefined) return null;
  return m.direction === 'higher' ? m.value >= m.target : m.value <= m.target;
}

function Ekg({ flat }: { flat: boolean }) {
  return (
    <svg className="ekg" viewBox="0 0 600 60" preserveAspectRatio="none" aria-hidden="true" data-flat={flat}>
      <path
        className={flat ? undefined : 'heartbeat__line'}
        d={flat ? 'M0 30H600' : 'M0 30H120l10-16 10 32 8-40 10 44 8-20H300l10-14 10 28 8-34 10 38 8-18H600'}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        style={flat ? undefined : { strokeDasharray: 1200, animationDuration: '2400ms' }}
      />
    </svg>
  );
}

function Sparkline({ history }: { history: { value: number }[] }) {
  if (history.length < 2) return null;
  const vs = history.map((h) => h.value);
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const d = vs.map((v, i) => `${i ? 'L' : 'M'}${(i / (vs.length - 1)) * 100},${hi === lo ? 10 : 18 - ((v - lo) / (hi - lo)) * 16}`).join(' ');
  return (
    <svg viewBox="0 0 100 20" style={{ inlineSize: 100, blockSize: 20 }} aria-hidden="true">
      <path d={d} fill="none" stroke="#9fd3ff" strokeWidth="1.5" />
    </svg>
  );
}

function MetricCard({ organ, m }: { organ: string; m: EvalMetric }) {
  const { t, fmt } = useLang();
  const pass = metricPasses(m);
  const oracle = organ === 'oracle';
  const val = m.unit ? `${fmt.num(m.value, 3)} ${m.unit}` : fmt.num(m.value, 3);
  return (
    <li className="metric" data-metric={m.id} {...(oracle ? { 'data-oracle-value': '' } : {})}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong dir="auto">{m.label}</strong>
        {oracle ? <ModeledLabel /> : null}
      </div>
      <div className="metric__value">
        <Bdi>{val}</Bdi>
      </div>
      <dl className="kv">
        <dt>{t('evals.target')}</dt>
        <dd>
          <Bdi>{m.target === null || m.target === undefined ? t('evals.targetNone') : m.unit ? `${fmt.num(m.target, 3)} ${m.unit}` : fmt.num(m.target, 3)}</Bdi>
        </dd>
        <dt>{t('evals.dataset')}</dt>
        <dd>
          <Bdi ltr className="mono">
            {m.dataset}
          </Bdi>
        </dd>
        <dt>{t('evals.time')}</dt>
        <dd>{fmt.dateTime(m.timestamp)}</dd>
        <dt>{t('evals.trend')}</dt>
        <dd>{m.history && m.history.length > 1 ? <Sparkline history={m.history} /> : <span className="muted">{t('evals.trendNone')}</span>}</dd>
      </dl>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="small muted" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <IconArrow dir={m.direction === 'higher' ? 'up' : 'down'} width={14} height={14} />
          {t(m.direction === 'higher' ? 'evals.dir.higher' : 'evals.dir.lower')}
        </span>
        <span className="metric__verdict" data-pass={pass === null ? undefined : String(pass)}>
          {pass === null ? <IconInfo /> : pass ? <IconCheck /> : <IconWarning />}
          {pass === null ? t('evals.noTarget') : pass ? t('evals.pass') : t('evals.fail')}
        </span>
        {m.mode ? <span className="chip chip--demo">{m.mode}</span> : null}
      </div>
    </li>
  );
}

export function EvalBody({ data, buildSha, now }: { data: EvalsLatest | null; buildSha?: string | null; now: number }) {
  const { t, fmt, dict } = useLang();
  const st = evalsState(data, now, buildSha);
  if (st === 'none')
    return (
      <div className="state" data-testid="evals-none">
        <p className="state__title">
          <IconInfo />
          {t('evals.none')}
        </p>
        <p className="small muted">{t('evals.noneBody')}</p>
        <Ekg flat />
      </div>
    );
  const organs = Object.entries(data?.organs ?? {}).sort(([a], [b]) => ORDER.indexOf(a) - ORDER.indexOf(b));
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {st === 'stale' ? (
        <div className="banner banner--offline" role="status" data-testid="evals-stale">
          <IconWarning />
          <span>{t('evals.stale', { time: fmt.dateTime(data?.generated_at) })}</span>
        </div>
      ) : null}
      <p className="small muted">{t('evals.generated', { time: fmt.dateTime(data?.generated_at), sha: data?.git_sha ?? '–' })}</p>
      <div className="evals-grid">
        {organs.map(([organ, o]: [string, EvalOrgan]) => (
          <section key={organ} className="panel vital" aria-labelledby={`ev-${organ}`} data-organ={organ}>
            <div className="panel__head">
              <IconPulse className="panel__icon" aria-hidden="true" />
              <h2 id={`ev-${organ}`}>{hasKey(dict, `organ.${organ}`) ? t(`organ.${organ}` as never) : organ}</h2>
              <span className="spacer chips">
                {o.status === 'pass' ? (
                  <span className="chip chip--validated">
                    <IconCheck />
                    {t('evals.pass')}
                  </span>
                ) : o.status === 'fail' ? (
                  <span className="chip chip--unvalidated">
                    <IconWarning />
                    {t('evals.fail')}
                  </span>
                ) : o.status === 'error' ? (
                  <span className="chip chip--disputed">
                    <IconWarning />
                    {t('section.status.unavailable')}
                  </span>
                ) : (
                  <span className="chip chip--demo">{t('evals.notRun')}</span>
                )}
              </span>
            </div>
            {o.metrics?.length ? (
              <ul className="claims">
                {o.metrics.map((m) => (
                  <MetricCard key={m.id} organ={organ} m={m} />
                ))}
              </ul>
            ) : (
              <p className="small muted">{o.status === 'error' ? t('evals.organError', { message: o.message ?? '' }) : t('evals.notRun')}</p>
            )}
          </section>
        ))}
      </div>
      <details className="disclosure">
        <summary>{t('evals.table')}</summary>
        <div className="table-wrap">
          <table className="data" data-testid="evals-table">
            <caption>{t('evals.title')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('evals.col.organ')}</th>
                <th scope="col">{t('evals.col.metric')}</th>
                <th scope="col" className="n">
                  {t('evals.value')}
                </th>
                <th scope="col" className="n">
                  {t('evals.target')}
                </th>
                <th scope="col">{t('drawer.result')}</th>
              </tr>
            </thead>
            <tbody>
              {organs.flatMap(([organ, o]) =>
                (o.metrics ?? []).map((m) => {
                  const pass = metricPasses(m);
                  return (
                    <tr key={m.id} {...(organ === 'oracle' ? { 'data-oracle-value': '' } : {})}>
                      <td>{hasKey(dict, `organ.${organ}`) ? t(`organ.${organ}` as never) : organ}</td>
                      <td dir="auto">
                        {m.label} {organ === 'oracle' ? <ModeledLabel /> : null}
                      </td>
                      <td className="n">{fmt.num(m.value, 3)}</td>
                      <td className="n">{m.target === null || m.target === undefined ? '–' : fmt.num(m.target, 3)}</td>
                      <td>{pass === null ? t('evals.noTarget') : pass ? t('evals.pass') : t('evals.fail')}</td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export function EvalHeartbeat() {
  const { t } = useLang();
  const [state, setState] = useState<{ k: 'loading' } | { k: 'ok'; data: EvalsLatest; sha?: string | null; now: number } | { k: 'error'; err: ApiError }>({ k: 'loading' });
  const load = useCallback(async () => {
    setState({ k: 'loading' });
    const [r, o] = await Promise.all([api.getEvals(), api.getOrgans()]);
    if (r.ok) setState({ k: 'ok', data: r.value, sha: o.ok ? o.value.build_sha : null, now: Date.now() });
    else setState({ k: 'error', err: r.error });
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);
  return (
    <section aria-labelledby="evals-title" style={{ display: 'grid', gap: 16 }} data-testid="evals">
      <div className="section-title">
        <h1 id="evals-title">{t('evals.title')}</h1>
        <span className="rule" aria-hidden="true" />
      </div>
      <p className="muted">{t('evals.subtitle')}</p>
      {state.k === 'ok' ? <Ekg flat={evalsState(state.data, state.now, state.sha) === 'none'} /> : null}
      {state.k === 'loading' ? (
        <div role="status">
          <span className="small muted">{t('evals.loading')}</span>
          <Skeleton block />
        </div>
      ) : null}
      {state.k === 'error' ? (
        <div className="state state--error" role="alert">
          <p className="state__title">
            <IconWarning />
            {t('evals.error', { reason: `${state.err.code}: ${state.err.message}` })}
          </p>
          <div>
            <button type="button" className="btn btn--small" onClick={() => void load()}>
              {t('evals.retry')}
            </button>
          </div>
        </div>
      ) : null}
      {state.k === 'ok' ? <EvalBody data={state.data} buildSha={state.sha} now={state.now} /> : null}
    </section>
  );
}
