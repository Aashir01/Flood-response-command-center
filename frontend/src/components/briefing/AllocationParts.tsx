'use client';
import { useMemo, useState } from 'react';
import type { OptimizeOut, ScenarioDistrict, SensitivityOut } from '@/api/types';
import { IconCoin, IconIdle, IconScale } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';
import { districtName, useDistrictMeta } from '@/lib/districts';

export function useCommodity() {
  const { t, dict } = useLang();
  return {
    name: (id: string) => (hasKey(dict, `commodity.${id}`) ? t(`commodity.${id}` as never) : id),
    unit: (u: string) => {
      const k = `unit.${u.replace(/^.*\bper\s+/, '').trim()}`;
      return hasKey(dict, k) ? t(k as never) : u.replace(/^.*\bper\s+/, '');
    },
  };
}

export function CostBenefit({ opt }: { opt: OptimizeOut }) {
  const { t, fmt } = useLang();
  return (
    <div className="stat-row" data-testid="cost-benefit">
      <div className="stat stat--flood">
        <span className="stat__label">{t('alloc.people')}</span>
        <span className="stat__value">{fmt.int(opt.cost_benefit.people_covered)}</span>
      </div>
      <div className="stat">
        <span className="stat__label">{t('alloc.costPer')}</span>
        <span className="stat__value">{fmt.num(opt.cost_benefit.cost_per_person_covered, 2)}</span>
      </div>
      <div className="stat">
        <span className="stat__label">{t('alloc.totalCost')}</span>
        <span className="stat__value">{fmt.compact(opt.total_cost)}</span>
      </div>
      <div className="stat">
        <span className="stat__label">{t('alloc.status')}</span>
        <span className="stat__value" style={{ fontSize: '1.05rem' }}>
          {t(`alloc.status.${opt.status}`)}
          <small>
            {' · '}
            {t('alloc.gap')}: {opt.optimality_gap === null || opt.optimality_gap === undefined ? t('alloc.gapNone') : fmt.pct(opt.optimality_gap, 2)}
          </small>
        </span>
      </div>
    </div>
  );
}

type SortKey = 'district' | 'coverage' | 'unreached';

export function AllocationTable({ opt, districts }: { opt: OptimizeOut; districts?: ScenarioDistrict[] }) {
  const { t, fmt, lang } = useLang();
  const meta = useDistrictMeta();
  const c = useCommodity();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'coverage', dir: -1 });
  const commodities = useMemo(() => [...new Set(opt.allocation.map((a) => a.commodity_id))], [opt]);
  const rows = useMemo(() => {
    const byD = new Map<string, Record<string, number>>();
    for (const a of opt.allocation) {
      const r = byD.get(a.district_id) ?? {};
      r[a.commodity_id] = a.quantity;
      byD.set(a.district_id, r);
    }
    const list = opt.coverage.map((cv) => ({
      id: cv.district_id,
      name: districtName(meta, cv.district_id, lang, districts?.find((d) => d.district_id === cv.district_id)?.name),
      q: byD.get(cv.district_id) ?? {},
      coverage: cv.fraction,
      access: cv.access_mode,
      unreached: cv.unreached_people,
    }));
    list.sort((a, b) => {
      const v = sort.key === 'district' ? a.name.localeCompare(b.name, lang) : (a[sort.key] as number) - (b[sort.key] as number);
      return v * sort.dir;
    });
    return list;
  }, [opt, meta, lang, districts, sort]);
  const th = (key: SortKey, label: string, numeric = false) => (
    <th scope="col" className={numeric ? 'n' : undefined} aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="sort-btn" onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : numeric ? -1 : 1 }))}>
        {label}
        <span aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  );
  return (
    <details className="disclosure">
      <summary>{t('alloc.table')}</summary>
      <div className="table-wrap">
        <table className="data" data-testid="allocation-table">
          <caption>{t('alloc.tableCaption')}</caption>
          <thead>
            <tr>
              {th('district', t('table.district'))}
              {commodities.map((k) => (
                <th scope="col" className="n" key={k}>
                  {c.name(k)}
                </th>
              ))}
              {th('coverage', t('table.coverage'), true)}
              <th scope="col">{t('table.access')}</th>
              {th('unreached', t('alloc.unreached'), true)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <th scope="row">
                  <Bdi>{r.name}</Bdi>
                </th>
                {commodities.map((k) => (
                  <td className="n" key={k}>
                    {fmt.int(r.q[k] ?? 0)}
                  </td>
                ))}
                <td className="n">{fmt.pct(r.coverage)}</td>
                <td>{t(`access.${r.access}`)}</td>
                <td className="n">{fmt.int(r.unreached)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function ShadowPricePanel({ sens }: { sens: SensitivityOut }) {
  const { t, fmt, lang } = useLang();
  const meta = useDistrictMeta();
  const c = useCommodity();
  const ranges = new Map(sens.ranges.map((r) => [r.constraint, r]));
  return (
    <section aria-labelledby="prices-title" data-testid="shadow-prices">
      <h3 id="prices-title" style={{ marginBlockEnd: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
        <IconScale width={20} height={20} aria-hidden="true" />
        {t('prices.title')}
      </h3>
      <ul className="prices">
        {sens.shadow_prices.map((sp) => {
          const [kind, id = ''] = sp.constraint.split(':');
          const value = fmt.sig(Math.abs(sp.value), 2);
          let text: string;
          if (!sp.binding) {
            const name = kind === 'supply' ? c.name(id) : kind === 'budget' ? t('alloc.totalCost') : kind === 'equity_floor' ? t('equity.slider') : districtName(meta, id, lang);
            text = t('prices.notBinding', { name });
          } else if (kind === 'supply') text = t('prices.binding', { unit: c.unit(sp.unit), commodity: c.name(id), value });
          else if (kind === 'budget') text = t('prices.budget', { value });
          else if (kind === 'equity_floor') text = t('prices.equity', { value });
          else text = t('prices.coverage', { district: districtName(meta, id, lang), value });
          const range = ranges.get(sp.constraint);
          return (
            <li key={sp.constraint} className="price" data-binding={sp.binding}>
              {sp.binding ? <IconCoin /> : <IconIdle />}
              <div>
                <p>{text}</p>
                <p className="small muted">
                  <Bdi ltr className="mono">
                    {sp.constraint}
                  </Bdi>{' '}
                  · <Bdi>{`${fmt.sig(sp.value, 3)} ${sp.unit}`}</Bdi>
                </p>
                {range ? <p className="small muted">{t('prices.range', { down: fmt.compact(range.allowable_decrease), up: fmt.compact(range.allowable_increase) })}</p> : null}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="small muted" style={{ marginBlockStart: 8 }}>
        {t('prices.basis')}
      </p>
    </section>
  );
}
