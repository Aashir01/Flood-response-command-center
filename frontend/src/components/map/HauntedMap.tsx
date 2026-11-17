'use client';
// The haunted ouija-board map (design section 8). Lazy chunk: MapLibre never counts toward first-load JS.
// Labels are DOM markers (correct Urdu shaping without glyph PBFs or the RTL text plugin).
import 'maplibre-gl/dist/maplibre-gl.css';
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, LngLatBoundsLike, Map as MlMap, StyleSpecification } from 'maplibre-gl';
import { useEffect, useLayoutEffect, useRef } from 'react';
import type { Lang } from '@/api/types';
import { bboxOf, labelVisible } from '@/lib/geo';
import { loadDistrictGeo } from '@/lib/districts';
import { coordsOf } from './mapData';

export type LayerKey = 'flood' | 'perm' | 'districts' | 'allocation' | 'reference';
export const LAYER_IDS: Record<LayerKey, string[]> = {
  flood: ['flood-fill', 'flood-glow-outer', 'flood-glow-mid', 'flood-edge'],
  perm: ['water-perm'],
  districts: ['districts-line'],
  allocation: ['allocation-circles'],
  reference: ['reference-line'],
};

export interface PopupRow {
  id: string;
  title: string;
  lines: [string, string][];
}

export interface HauntedMapProps {
  lang: Lang;
  layers: Record<LayerKey, boolean>;
  flood: unknown;
  reference: unknown;
  allocation: unknown;
  names: Map<string, string>;
  popupFor: (districtId: string) => PopupRow | null;
  reducedMotion: boolean;
  label: string;
  onUnavailable: () => void;
  onToggleTable: () => void;
  attribution: string;
}

const SINDH: LngLatBoundsLike = [
  [66.4, 23.6],
  [71.2, 28.6],
];

function webglAvailable(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

async function loadStyle(): Promise<StyleSpecification> {
  const r = await fetch('/map/style.json');
  const style = (await r.json()) as StyleSpecification;
  const origin = window.location.origin;
  for (const src of Object.values(style.sources)) {
    const s = src as { type: string; data?: unknown };
    if (s.type === 'geojson' && typeof s.data === 'string' && s.data.startsWith('/')) s.data = `${origin}${s.data}`;
  }
  return style;
}

export default function HauntedMap(props: HauntedMapProps) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markers = useRef<{ id: string; el: HTMLElement; marker: maplibregl.Marker; bbox: [number, number, number, number] | null }[]>([]);
  const ready = useRef(false);
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });
  const fitted = useRef(false);

  // Create the map once.
  useEffect(() => {
    if (!host.current) return;
    if (!webglAvailable()) {
      props.onUnavailable();
      return;
    }
    let disposed = false;
    let created: MlMap | null = null;
    void (async () => {
      try {
        maplibregl.setWorkerUrl(`${window.location.origin}/vendor/maplibre-gl-worker.mjs`);
        const style = await loadStyle();
        if (disposed || !host.current) return;
        const map: MlMap = new maplibregl.Map({
          container: host.current,
          style,
          bounds: SINDH,
          fitBoundsOptions: { padding: 24 },
          attributionControl: { compact: true, customAttribution: propsRef.current.attribution },
          dragRotate: false,
          pitchWithRotate: false,
          touchPitch: false,
          maxZoom: 11,
          minZoom: 4,
          fadeDuration: 0,
        });
        created = map;
        mapRef.current = map;
        map.touchZoomRotate.disableRotation();
        map.keyboard.disableRotation();
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        const canvas = map.getCanvas();
        canvas.setAttribute('aria-label', propsRef.current.label);
        canvas.setAttribute('role', 'application');
        canvas.addEventListener('webglcontextlost', () => propsRef.current.onUnavailable());
        map.on('error', (e) => {
          if (String((e as unknown as { error?: { message?: string } }).error?.message ?? '').toLowerCase().includes('webgl')) propsRef.current.onUnavailable();
        });

        const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, className: 'map-popup', maxWidth: '280px' });
        const showPopup = (id: string, lngLat: maplibregl.LngLatLike) => {
          const row = propsRef.current.popupFor(id);
          if (!row) return;
          const root = document.createElement('div');
          root.setAttribute('dir', propsRef.current.lang === 'ur' ? 'rtl' : 'ltr');
          root.setAttribute('lang', propsRef.current.lang);
          const h = document.createElement('strong');
          h.textContent = row.title;
          root.appendChild(h);
          const dl = document.createElement('dl');
          dl.className = 'kv';
          dl.style.marginBlockStart = '6px';
          for (const [k, v] of row.lines) {
            const dt = document.createElement('dt');
            dt.textContent = k;
            const dd = document.createElement('dd');
            const b = document.createElement('bdi');
            b.textContent = v;
            dd.appendChild(b);
            dl.append(dt, dd);
          }
          root.appendChild(dl);
          popup.setLngLat(lngLat).setDOMContent(root).addTo(map);
        };
        map.on('click', 'allocation-circles', (e) => {
          const id = e.features?.[0]?.properties?.district_id as string | undefined;
          if (id) showPopup(id, e.lngLat);
        });
        map.on('mouseenter', 'allocation-circles', () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'allocation-circles', () => {
          map.getCanvas().style.cursor = '';
        });

        map.on('load', async () => {
          if (disposed) return;
          ready.current = true;
          // DOM labels with browser text shaping, decluttered by projected area.
          const geo = await loadDistrictGeo();
          for (const f of geo?.features ?? []) {
            const el = document.createElement('span');
            el.className = 'map-label';
            el.setAttribute('aria-hidden', 'true');
            const bdi = document.createElement('bdi');
            el.appendChild(bdi);
            const marker = new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(f.properties.centroid).addTo(map);
            markers.current.push({ id: f.properties.district_id, el, marker, bbox: bboxOf(coordsOf(f.geometry)) });
          }
          applyAll();
        });
        map.on('zoomend', () => declutter());
        map.on('moveend', () => declutter());
      } catch {
        propsRef.current.onUnavailable();
      }
    })();
    return () => {
      disposed = true;
      for (const m of markers.current) m.marker.remove();
      markers.current = [];
      created?.remove();
      mapRef.current = null;
      ready.current = false;
    };
    // The map is created once; later prop changes are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function declutter() {
    const map = mapRef.current;
    if (!map) return;
    for (const m of markers.current) {
      if (!m.bbox) continue;
      const a = map.project([m.bbox[0], m.bbox[1]]);
      const b = map.project([m.bbox[2], m.bbox[3]]);
      const area = Math.abs(b.x - a.x) * Math.abs(b.y - a.y);
      m.el.hidden = !labelVisible(area) || !propsRef.current.layers.districts;
    }
  }

  function applyAll() {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const p = propsRef.current;
    (map.getSource('flood') as GeoJSONSource | undefined)?.setData(p.flood as GeoJSON.FeatureCollection);
    (map.getSource('reference') as GeoJSONSource | undefined)?.setData(p.reference as GeoJSON.FeatureCollection);
    (map.getSource('allocation') as GeoJSONSource | undefined)?.setData(p.allocation as GeoJSON.FeatureCollection);
    for (const [key, ids] of Object.entries(LAYER_IDS) as [LayerKey, string[]][])
      for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', p.layers[key] ? 'visible' : 'none');
    for (const m of markers.current) {
      const bdi = m.el.firstChild as HTMLElement;
      bdi.textContent = p.names.get(m.id) ?? '';
      m.el.setAttribute('lang', p.lang);
    }
    declutter();
    const fc = p.flood as { features?: unknown[] };
    if (!fitted.current && fc.features?.length) {
      fitted.current = true;
      const coords = fc.features.flatMap((f) => coordsOf((f as { geometry: unknown }).geometry));
      const bb = bboxOf(coords);
      if (bb) map.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 40, maxZoom: 8, animate: !p.reducedMotion, duration: p.reducedMotion ? 0 : 800 });
    }
  }

  useEffect(() => {
    applyAll();
  });

  return (
    <div
      ref={host}
      className="map-canvas"
      dir="ltr"
      data-testid="map-canvas"
      onKeyDown={(e) => {
        if ((e.key === 't' || e.key === 'T') && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          props.onToggleTable();
        }
      }}
    />
  );
}
