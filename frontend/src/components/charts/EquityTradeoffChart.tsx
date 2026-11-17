'use client';
// Coverage versus equity floor (FRN-R5.7). The slider snaps to precomputed points; nothing is re-solved or
// interpolated, and no line is drawn across or into an infeasible floor (FRN-P7).
import { useId, useMemo, useState } from 'react';
import { IconWarning } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';
import { buildSegments, type EquityPoint } from '@/lib/equitySegments';
import { linear, linePath, niceTicks } from '@/lib/scale';

const W = 640;
const H = 280;
const M = { top: 20, right: 20, bottom: 48, left: 72 };

export function EquityTradeoffChart({ points, currentFloor, equityCost }: { points: EquityPoint[]; currentFloor?: number | null; equityCost?: number | null }) {
  const { t, fmt } = useLang();
  const uid = useId();
  const { sorted, segments, infeasible } = useMemo(() => buildSegments(points), [points]);
  const initial = useMemo(() => {
    if (typeof currentFloor !== 'number') return 0;
    let best = 0;
    sorted.forEach((p, i) => {
      if (Math.abs(p.min_coverage_floor - currentFloor) < Math.abs((sorted[best]?.min_coverage_floor ?? 0) - currentFloor)) best = i;
    });
    return best;
  }, [sorted, currentFloor]);
  const [idx, setIdx] = useState(initial);
  if (!sorted.length) return null;
  const sel = sorted[Math.min(idx, sorted.length - 1)] as EquityPoint;

  const f0 = sorted[0]?.min_coverage_floor ?? 0;
  const f1 = sorted.at(-1)?.min_coverage_floor ?? 1;
  const x = linear([f0, f1 === f0 ? f0 + 1 : f1], [M.left, W - M.right]);
  const vals = sorted.filter((p) => p.total_coverage !== null && p.status !== 'infeasible').map((p) => p.total_coverage as number);
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 1;
  const pad = (hi - lo || hi || 1) * 0.15;
  const ticks = niceTicks(Math.max(0, lo - pad), hi + pad, 4);
  const y = linear([ticks[0] ?? lo, ticks.at(-1) ?? hi], [H - M.bottom, M.top]);
  const step = sorted.length > 1 ? (x(f1) - x(f0)) / (sorted.length - 1) : 40;
  const floorTxt = (f: number) => fmt.pct(f);
  const valueText = (p: EquityPoint) =>
    p.status === 'infeasible' || p.people_covered === null
      ? t('equity.valueInfeasible', { floor: floorTxt(p.min_coverage_floor) })
      : t('equity.valueFeasible', { floor: floorTxt(p.min_coverage_floor), people: fmt.int(p.people_covered) });
  const firstFeasible = segments[0]?.[0];
  const lastFeasible = segments.at(-1)?.at(-1);
  const summary =
    firstFeasible && lastFeasible
      ? infeasible.length
        ? t('equity.summary', {
            from: fmt.int(firstFeasible.total_coverage),
            to: fmt.int(lastFeasible.total_coverage),
            f0: floorTxt(firstFeasible.min_coverage_floor),
            f1: floorTxt(lastFeasible.min_coverage_floor),
            inf: floorTxt(infeasible[0]?.fromFloor ?? 1),
          })
        : t('equity.summaryAllFeasible', {
            from: fmt.int(firstFeasible.total_coverage),
            to: fmt.int(lastFeasible.total_coverage),
            f0: floorTxt(firstFeasible.min_coverage_floor),
            f1: floorTxt(lastFeasible.min_coverage_floor),
          })
      : '';

  return (
    <figure className="chart" data-testid="equity-chart">
      <figcaption>
        <strong>{t('equity.title')}</strong>
      </figcaption>
      <p className="small muted">{t('equity.help')}</p>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} direction="ltr">
        <defs>
          <pattern id={`${uid}-hatch`} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill="#ff9d3c14" />
            <line x1="0" y1="0" x2="0" y2="8" stroke="#ff9d3c" strokeOpacity=".55" strokeWidth="2" />
          </pattern>
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
          {sorted.map((p) => (
            <text key={p.min_coverage_floor} x={x(p.min_coverage_floor)} y={H - M.bottom + 16} textAnchor="middle">
              {floorTxt(p.min_coverage_floor)}
            </text>
          ))}
          <text x={(M.left + W - M.right) / 2} y={H - 8} textAnchor="middle">
            {t('equity.axisX')}
          </text>
          <line x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom} />
        </g>
        {infeasible.map((r) => {
          const xa = Math.max(M.left, x(r.fromFloor) - step / 2);
          const xb = Math.min(W - M.right, x(r.toFloor) + step / 2);
          return (
            <g key={r.fromIndex} data-infeasible-range={`${r.fromIndex}-${r.toIndex}`}>
              <rect x={xa} y={M.top} width={Math.max(4, xb - xa)} height={H - M.bottom - M.top} fill={`url(#${uid}-hatch)`} />
              <text className="label" x={(xa + xb) / 2} y={M.top + 16} textAnchor="middle" style={{ fill: '#ffc58f', fontWeight: 700 }}>
                {xb - xa > 120 ? t('equity.infeasible') : '✕'}
              </text>
            </g>
          );
        })}
        {segments.map((seg) => (
          <path
            key={seg[0]?.min_coverage_floor}
            className="feasible-line"
            data-segment={seg.map((p) => p.min_coverage_floor).join(',')}
            d={linePath(seg.map((p) => ({ x: x(p.min_coverage_floor), y: y(p.total_coverage as number) })))}
          />
        ))}
        {segments.flat().map((p) => (
          <circle key={p.min_coverage_floor} className="feasible-dot" cx={x(p.min_coverage_floor)} cy={y(p.total_coverage as number)} r="3.5" />
        ))}
        {typeof currentFloor === 'number' ? (
          <g>
            <line className="current" x1={x(currentFloor)} x2={x(currentFloor)} y1={M.top} y2={H - M.bottom} />
            <text className="label" x={x(currentFloor) + 4} y={H - M.bottom - 6}>
              {t('equity.current', { floor: floorTxt(currentFloor) })}
            </text>
          </g>
        ) : null}
        <line className="selected" x1={x(sel.min_coverage_floor)} x2={x(sel.min_coverage_floor)} y1={M.top} y2={H - M.bottom} />
        {sel.total_coverage !== null && sel.status !== 'infeasible' ? (
          <circle cx={x(sel.min_coverage_floor)} cy={y(sel.total_coverage)} r="6" fill="none" stroke="#9fd3ff" strokeWidth="2" />
        ) : null}
      </svg>
      <div className="field">
        <label htmlFor={`${uid}-slider`}>{t('equity.slider')}</label>
        <input
          id={`${uid}-slider`}
          className="slider"
          type="range"
          min={0}
          max={sorted.length - 1}
          step={1}
          value={idx}
          aria-valuetext={valueText(sel)}
          onChange={(e) => setIdx(Number(e.target.value))}
          dir="ltr"
          data-testid="equity-slider"
        />
      </div>
      <p aria-live="polite" data-testid="equity-readout" className={sel.status === 'infeasible' ? 'state state--error' : 'small'}>
        {sel.status === 'infeasible' ? (
          <span className="state__title">
            <IconWarning />
            {t('equity.valueInfeasible', { floor: floorTxt(sel.min_coverage_floor) })}. {t('equity.infeasible')}.
          </span>
        ) : (
          <>
            {t('equity.selected', { floor: floorTxt(sel.min_coverage_floor) })}: {valueText(sel)}
            {sel.total_coverage !== null ? ` · ${t('equity.col.coverage')} ${fmt.int(sel.total_coverage)}` : ''}
          </>
        )}
      </p>
      {typeof equityCost === 'number' ? <p className="small">{t('equity.cost', { value: fmt.int(equityCost) })}</p> : null}
      <details className="disclosure">
        <summary>{t('forecast.table')}</summary>
        <div className="table-wrap">
          <table className="data" data-testid="equity-table">
            <caption>{t('equity.title')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('equity.col.floor')}</th>
                <th scope="col">{t('equity.col.status')}</th>
                <th scope="col" className="n">
                  {t('equity.col.coverage')}
                </th>
                <th scope="col" className="n">
                  {t('equity.col.people')}
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.min_coverage_floor}>
                  <td>{floorTxt(p.min_coverage_floor)}</td>
                  <td>{t(`alloc.status.${p.status}`)}</td>
                  <td className="n">{p.status === 'infeasible' ? '–' : fmt.int(p.total_coverage)}</td>
                  <td className="n">{p.status === 'infeasible' ? '–' : fmt.int(p.people_covered)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
