'use client';
// District names and centroids from the self-hosted boundary file (same ids as the Ledger demo dataset).
import { useEffect, useState } from 'react';
import type { Lang } from '@/api/types';

export interface DistrictMeta {
  id: string;
  en: string;
  ur: string;
  centroid: [number, number];
}
export interface DistrictGeo {
  type: 'FeatureCollection';
  attribution?: string;
  features: { type: 'Feature'; properties: { district_id: string; name_en: string; name_ur: string; centroid: [number, number] }; geometry: unknown }[];
}

let promise: Promise<DistrictGeo | null> | null = null;
export function loadDistrictGeo(): Promise<DistrictGeo | null> {
  promise ??= fetch('/map/districts.geojson')
    .then((r) => (r.ok ? (r.json() as Promise<DistrictGeo>) : null))
    .catch(() => null);
  return promise;
}

export function useDistrictMeta(): Map<string, DistrictMeta> {
  const [meta, setMeta] = useState<Map<string, DistrictMeta>>(() => new Map());
  useEffect(() => {
    let alive = true;
    void loadDistrictGeo().then((g) => {
      if (!alive || !g) return;
      setMeta(new Map(g.features.map((f) => [f.properties.district_id, { id: f.properties.district_id, en: f.properties.name_en, ur: f.properties.name_ur, centroid: f.properties.centroid }])));
    });
    return () => {
      alive = false;
    };
  }, []);
  return meta;
}

export function districtName(meta: Map<string, DistrictMeta>, id: string, lang: Lang, fallback?: string): string {
  const m = meta.get(id);
  if (m) return lang === 'ur' ? m.ur || m.en : m.en;
  return fallback ?? id.replace(/^pk-sindh-/, '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
