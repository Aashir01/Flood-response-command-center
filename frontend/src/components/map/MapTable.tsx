'use client';
import { useMemo, useState } from 'react';
import { useCommodity } from '@/components/briefing/AllocationParts';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { districtName, type DistrictMeta } from '@/lib/districts';
import type { DistrictRow } from './mapData';

type Key = 'name' | 'floodedKm2' | 'floodedFraction' | 'population' | 'coverage';

/** The map's table alternative: a real, sortable <table> built from the same rows as the map (FRN-R4.5). */
export function MapTable({ rows, meta }: { rows: DistrictRow[]; meta: Map<string, DistrictMeta> }) {
  const { t, fmt, lang } = useLang();
  const c = useCommodity();
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: 'floodedKm2', dir: -1 });
  const named = useMemo(() => rows.map((r) => ({ ...r, name: districtName(meta, r.id, lang) })), [rows, meta, lang]);
  const sorted = useMemo(() => {
    const v = (r: (typeof named)[number]) => (sort.key === 'name' ? r.name : (r[sort.key] ?? -Infinity));
    return [...named].sort((a, b) => {
      const x = v(a);
      const y = v(b);
      return (typeof x === 'string' && typeof y === 'string' ? x.localeCompare(y, lang) : (x as number) - (y as number)) * sort.dir;
    });
  }, [named, sort, lang]);
  const th = (key: Key, label: string, numeric = true) => (
    <th scope="col" className={numeric ? 'n' : undefined} aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        className="sort-btn"
        aria-label={t('table.sortBy', { column: label })}
        onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : numeric ? -1 : 1 }))}
      >
        {label}
        <span aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  );
  if (!rows.length) return <p className="small muted">{t('table.empty')}</p>;
  return (
    <div className="table-wrap">
      <table className="data" tabIndex={-1} data-testid="map-table">
        <caption>{t('table.caption')}</caption>
        <thead>
          <tr>
            {th('name', t('table.district'), false)}
            {th('floodedKm2', t('table.flooded'))}
            {th('floodedFraction', t('table.fraction'))}
            {th('population', t('table.population'))}
            <th scope="col">{t('table.allocation')}</th>
            {th('coverage', t('table.coverage'))}
            <th scope="col">{t('table.access')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id} data-district={r.id}>
              <th scope="row">
                <Bdi>{r.name}</Bdi>
              </th>
              <td className="n">{fmt.num(r.floodedKm2)}</td>
              <td className="n">{fmt.pct(r.floodedFraction)}</td>
              <td className="n">{fmt.int(r.population)}</td>
              <td>
                {Object.keys(r.allocation).length
                  ? Object.entries(r.allocation).map(([k, q]) => (
                      <div key={k} className="small">
                        {c.name(k)}: <Bdi>{fmt.int(q)}</Bdi>
                      </div>
                    ))
                  : '–'}
              </td>
              <td className="n">{fmt.pct(r.coverage)}</td>
              <td>{r.access ? t(`access.${r.access}` as MessageKey) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
