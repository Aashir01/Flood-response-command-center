'use client';
// Hand-rolled SVG forecast band (design section 9.1). The time axis stays left to right in RTL.
import { useId } from 'react';
import type { ForecastOut } from '@/api/types';
import { ModeledLabel } from '@/components/briefing/labels';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { bandPath, linear, linePath, niceTicks } from '@/lib/scale';

const W = 640;
const H = 300;
const M = { top: 16, right: 16, bottom: 92, left: 64 };
const STRIP = 34;

export function forecastDomain(f: Pick<ForecastOut, 'forecast' | 'danger_threshold_m3s'>): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of f.forecast) {
    lo = Math.min(lo, p.discharge.p10);
    hi = Math.max(hi, p.discharge.p90);
  }
  if (typeof f.danger_threshold_m3s === 'number') {
    lo = Math.min(lo, f.danger_threshold_m3s);
    hi = Math.max(hi, f.danger_threshold_m3s);
  }
  if (!Number.isFinite(lo)) return [0, 1];
  const pad = (hi - lo || hi || 1) * 0.12;
  return [Math.max(0, lo - pad), hi + pad];
}

export function ForecastBandChart({ forecast }: { forecast: ForecastOut }) {
  const { t, fmt } = useLang();
  const uid = useId();
  const pts = forecast.forecast;
  const n = pts.length;
  const [d0, d1] = forecastDomain(forecast);
  const ticks = niceTicks(d0, d1, 5);
  const y = linear([ticks[0] ?? d0, ticks.at(-1) ?? d1], [H - M.bottom, M.top]);
  const x = (i: number) => (n <= 1 ? (M.left + W - M.right) / 2 : M.left + (i * (W - M.left - M.right)) / (n - 1));
  const band = bandPath(
    pts.map((p, i) => ({ x: x(i), p10: p.discharge.p10, p50: p.discharge.p50, p90: p.discharge.p90 })),
    y,
  );
  const median = linePath(pts.map((p, i) => ({ x: x(i), y: y(p.discharge.p50) })));
  const thr = forecast.danger_threshold_m3s;
  const exceed = new Map(forecast.exceedance_prob.map((e) => [e.date, e.p_exceed]));
  const stripTop = H - M.bottom + 40;
  const p50s = pts.map((p) => p.discharge.p50);
  const station = forecast.station?.name ?? forecast.station_id;
  const summary = t('forecast.chartSummary', {
    station,
    from: fmt.date(pts[0]?.date),
    to: fmt.date(pts.at(-1)?.date),
    min: fmt.int(Math.min(...p50s)),
    max: fmt.int(Math.max(...p50s)),
    threshold: typeof thr === 'number' ? fmt.int(thr) : '–',
  });
  const unit = <Bdi>m³/s</Bdi>;

  return (
    <figure className="chart" data-oracle-value="" data-testid="forecast-chart">
      <figcaption>
        <strong>{t('forecast.chartTitle')}</strong> ({unit}) <ModeledLabel label={forecast.target_label} />
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${summary} ${t('label.modeled')}`} direction="ltr">
        <defs>
          <linearGradient id={`${uid}-fade`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#9fd3ff" stopOpacity=".35" />
            <stop offset="1" stopColor="#9fd3ff" stopOpacity=".12" />
          </linearGradient>
        </defs>
        <g className="grid">
          {ticks.map((v) => (
            <line key={v} x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} />
          ))}
        </g>
        <g className="axis">
          {ticks.map((v) => (
            <text key={v} x={M.left - 8} y={y(v) + 4} textAnchor="end">
              {fmt.compact(v)}
            </text>
          ))}
          {pts.map((p, i) => (
            <text key={p.date} x={x(i)} y={H - M.bottom + 16} textAnchor="middle">
              {fmt.date(p.date).replace(/\s\d{4}$/, '')}
            </text>
          ))}
          <line x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom} />
        </g>
        <path d={band} className="band" fill={`url(#${uid}-fade)`} style={{ fill: `url(#${uid}-fade)` }} />
        {typeof thr === 'number' ? (
          <g>
            <line className="threshold" x1={M.left} x2={W - M.right} y1={y(thr)} y2={y(thr)} />
            <text className="threshold-label" x={W - M.right} y={y(thr) - 6} textAnchor="end">
              {`${t('forecast.legend.threshold')} ${fmt.int(thr)} m³/s`}
            </text>
          </g>
        ) : null}
        <path d={median} className="median" />
        {pts.map((p, i) => (
          <circle key={p.date} cx={x(i)} cy={y(p.discharge.p50)} r="3" fill="#07090c" stroke="#9fd3ff" strokeWidth="1.5" />
        ))}
        {/* exceedance strip */}
        <text className="label" x={M.left - 8} y={stripTop + STRIP / 2 + 4} textAnchor="end" style={{ fill: '#ffc58f' }}>
          P
        </text>
        {pts.map((p, i) => {
          const pe = exceed.get(p.date);
          if (pe === undefined) return null;
          const bw = Math.max(8, Math.min(40, (W - M.left - M.right) / Math.max(1, n) - 10));
          const h = Math.max(1, pe * STRIP);
          return (
            <g key={p.date}>
              <rect className="exceed" x={x(i) - bw / 2} y={stripTop + STRIP - h} width={bw} height={h} rx="2" />
              <text className="label" x={x(i)} y={stripTop + STRIP + 13} textAnchor="middle">
                {fmt.pct(pe)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend" aria-hidden="true">
        <span>
          <span className="legend__swatch" style={{ background: '#9fd3ff40' }} />
          {t('forecast.legend.band')}
        </span>
        <span>
          <span className="legend__swatch" style={{ background: 'none', borderBlockEnd: '2px solid #9fd3ff', blockSize: 2 }} />
          {t('forecast.legend.median')}
        </span>
        <span>
          <span className="legend__swatch" style={{ background: 'none', borderBlockEnd: '2px dashed #ff9d3c', blockSize: 2 }} />
          {t('forecast.legend.threshold')}
        </span>
        <span>
          <span className="legend__swatch" style={{ background: '#ff9d3cb3' }} />
          {t('forecast.legend.exceed')}
        </span>
      </div>
      <details className="disclosure">
        <summary>{t('forecast.table')}</summary>
        <div className="table-wrap">
          <table className="data" data-testid="forecast-table">
            <caption>
              {t('forecast.chartTitle')} <ModeledLabel />
            </caption>
            <thead>
              <tr>
                <th scope="col">{t('forecast.col.date')}</th>
                <th scope="col" className="n">
                  {t('forecast.col.lead')}
                </th>
                <th scope="col" className="n">
                  <Bdi>{t('forecast.col.p10')}</Bdi>
                </th>
                <th scope="col" className="n">
                  <Bdi>{t('forecast.col.p50')}</Bdi>
                </th>
                <th scope="col" className="n">
                  <Bdi>{t('forecast.col.p90')}</Bdi>
                </th>
                <th scope="col" className="n">
                  {t('forecast.col.exceed')}
                </th>
              </tr>
            </thead>
            <tbody>
              {pts.map((p) => (
                <tr key={p.date}>
                  <td>
                    <Bdi>{fmt.date(p.date)}</Bdi>
                  </td>
                  <td className="n">{fmt.int(p.lead_days)}</td>
                  <td className="n">{fmt.int(p.discharge.p10)}</td>
                  <td className="n">{fmt.int(p.discharge.p50)}</td>
                  <td className="n">{fmt.int(p.discharge.p90)}</td>
                  <td className="n">{exceed.has(p.date) ? fmt.pct(exceed.get(p.date)) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
