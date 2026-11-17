'use client';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { IconTable, IconWarning } from '@/components/icons';
import { LabelChip } from '@/components/briefing/labels';
import { Skeleton } from '@/components/shell/Panel';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { districtName, useDistrictMeta } from '@/lib/districts';
import { useBench } from '@/state/BenchProvider';
import { useToolDocs } from '@/state/docs';
import { usePrefs } from '@/state/prefs';
import { useCommodity } from '@/components/briefing/AllocationParts';
import type { LayerKey, PopupRow } from './HauntedMap';
import { allocationFeatures, buildRows, EMPTY_FC, floodCollection } from './mapData';
import { MapTable } from './MapTable';

const HauntedMap = dynamic(() => import('./HauntedMap'), { ssr: false, loading: () => <div className="map-canvas"><Skeleton block lines={0} /></div> });

function useNearViewport<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === 'undefined') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no observer: mount at once
      setNear(true);
      return;
    }
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), { rootMargin: '300px' });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  return [ref, near];
}

export function MapSection() {
  const { t, lang, fmt } = useLang();
  const { state } = useBench();
  const { reducedMotion } = usePrefs();
  const docs = useToolDocs();
  const meta = useDistrictMeta();
  const c = useCommodity();
  const ids = useId();
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({ flood: true, perm: true, districts: true, allocation: true, reference: false });
  const [showTable, setShowTable] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [boardRef, near] = useNearViewport<HTMLDivElement>();
  const tableRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(
    () => buildRows([...meta.keys()], new Map([...meta.values()].map((m) => [m.id, m.centroid])), docs.compare, docs.optimize, docs.districts),
    [meta, docs.compare, docs.optimize, docs.districts],
  );
  const names = useMemo(() => new Map([...meta.values()].map((m) => [m.id, lang === 'ur' ? m.ur : m.en])), [meta, lang]);
  const flood = useMemo(() => floodCollection(docs.segment), [docs.segment]);
  const reference = docs.segment?.reference_overlay_geojson ?? null;
  const allocation = useMemo(() => (docs.optimize ? allocationFeatures(rows) : EMPTY_FC), [rows, docs.optimize]);
  const eyes = state.organs.eyes.state;
  const running = state.run.status === 'running' || state.run.status === 'starting';
  const tableOpen = showTable || unavailable;

  const toggleTable = useCallback(() => {
    setShowTable((v) => {
      const next = !v;
      if (next) requestAnimationFrame(() => tableRef.current?.querySelector<HTMLElement>('table')?.focus());
      return next;
    });
  }, []);
  const onUnavailable = useCallback(() => setUnavailable(true), []);

  const popupFor = useCallback(
    (id: string): PopupRow | null => {
      const r = rows.find((x) => x.id === id);
      if (!r) return null;
      const lines: [string, string][] = [];
      if (r.floodedKm2 !== null) lines.push([t('map.popup.flooded'), `${fmt.num(r.floodedKm2)} km² (${fmt.pct(r.floodedFraction)})`]);
      for (const [k, q] of Object.entries(r.allocation)) lines.push([c.name(k), fmt.int(q)]);
      if (r.coverage !== null) lines.push([t('map.popup.coverage'), fmt.pct(r.coverage)]);
      if (r.access) lines.push([t('map.popup.access'), t(`access.${r.access}` as MessageKey)]);
      if (r.unreached !== null) lines.push([t('map.popup.unreached'), fmt.int(r.unreached)]);
      return { id, title: districtName(meta, id, lang), lines };
    },
    [rows, t, fmt, c, meta, lang],
  );

  const status = !state.briefing && !running && !docs.segment ? 'empty' : running && !docs.segment && eyes !== 'unwell' ? 'loading' : eyes === 'unwell' ? 'eyes-unwell' : 'ready';
  const toggles: [LayerKey, MessageKey][] = [
    ['flood', 'map.layer.flood'],
    ['perm', 'map.layer.perm'],
    ['districts', 'map.layer.districts'],
    ['allocation', 'map.layer.allocation'],
  ];
  if (reference) toggles.push(['reference', 'map.layer.reference']);

  return (
    <section aria-labelledby={`${ids}-title`} role="region" id="map" className="map-col" data-testid="map-section">
      <div className="section-title">
        <h2 id={`${ids}-title`}>{t('map.title')}</h2>
        <span className="rule" aria-hidden="true" />
        {state.briefing || docs.segment ? <LabelChip label={state.briefing?.mode ?? 'demo'} /> : null}
      </div>
      <div className="board" ref={boardRef}>
        <span className="board__engrave board__engrave--tl" aria-hidden="true">
          ☾ N
        </span>
        <span className="board__engrave board__engrave--tr" aria-hidden="true">
          ✶ ✶ ✶
        </span>
        {unavailable ? (
          <div className="map-canvas">
            <div className="map-unavailable" role="status">
              <IconWarning width={28} height={28} style={{ justifySelf: 'center', color: '#ff9d3c' }} />
              <p>{t('map.unavailable')}</p>
            </div>
          </div>
        ) : near ? (
          <HauntedMap
            lang={lang}
            layers={layers}
            flood={flood}
            reference={reference ?? EMPTY_FC}
            allocation={allocation}
            names={names}
            popupFor={popupFor}
            reducedMotion={reducedMotion}
            label={`${t('map.region')}. ${t('map.instructions')}`}
            onUnavailable={onUnavailable}
            onToggleTable={toggleTable}
            attribution={t('map.attribution')}
          />
        ) : (
          <div className="map-canvas">
            <Skeleton block lines={0} />
          </div>
        )}
      </div>
      <p className="small muted" style={{ marginBlockStart: 8 }} id={`${ids}-instr`}>
        {t('map.instructions')}
      </p>
      {status === 'empty' ? (
        <p className="state small muted" role="status" style={{ marginBlockStart: 8 }}>
          {t('map.empty')}
        </p>
      ) : status === 'loading' ? (
        <p className="state small muted" role="status" style={{ marginBlockStart: 8 }}>
          {t('map.loading')}
        </p>
      ) : status === 'eyes-unwell' ? (
        <p className="state state--error small" role="status" style={{ marginBlockStart: 8 }}>
          <span className="state__title">
            <IconWarning />
            {t('map.eyesUnwell')}
          </span>
        </p>
      ) : null}
      <div className="map-controls">
        <fieldset className="layer-toggles">
          <legend>{t('map.layers')}</legend>
          {toggles.map(([k, key]) => (
            <label className="check" key={k}>
              <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} data-layer={k} />
              {t(key)}
            </label>
          ))}
        </fieldset>
        <button type="button" className="btn btn--small" aria-expanded={tableOpen} aria-controls={`${ids}-table`} onClick={toggleTable} disabled={unavailable}>
          <IconTable />
          {tableOpen ? t('map.hideTable') : t('map.showTable')}
        </button>
      </div>
      <div className="legend" aria-label={t('map.layers')}>
        <span>
          <span className="legend__swatch legend__swatch--flood" aria-hidden="true" />
          {t('map.legend.flood')}
        </span>
        <span>
          <span className="legend__swatch legend__swatch--perm" aria-hidden="true" />
          {t('map.legend.perm')}
        </span>
        <span>
          <span className="legend__swatch legend__swatch--alloc" aria-hidden="true" />
          {t('map.legend.alloc')}
        </span>
        {reference ? (
          <span>
            <span className="legend__swatch legend__swatch--ref" aria-hidden="true" />
            {t('map.legend.ref')}
          </span>
        ) : null}
      </div>
      {reference && layers.reference && docs.segment?.reference_overlay_note ? (
        <p className="small muted" style={{ marginBlockStart: 6 }}>
          <Bdi>{t('map.reference.note', { note: docs.segment.reference_overlay_note })}</Bdi>
        </p>
      ) : null}
      <div id={`${ids}-table`} ref={tableRef} hidden={!tableOpen} style={{ marginBlockStart: 12 }}>
        <MapTable rows={rows} meta={meta} />
      </div>
    </section>
  );
}
