// Pure builders that turn organ outputs into map layers and table rows. The map and the table read the
// same rows, so the table alternative always matches the map (FRN-R4.5).
import type { CompareOut, OptimizeOut, ScenarioDistrict, SegmentOut } from '@/api/types';

export interface DistrictRow {
  id: string;
  floodedKm2: number | null;
  floodedFraction: number | null;
  population: number | null;
  allocation: Record<string, number>;
  coverage: number | null;
  access: 'road' | 'air_boat' | 'unreachable' | null;
  unreached: number | null;
  peopleCovered: number | null;
  centroid?: [number, number];
}

export function buildRows(
  ids: string[],
  centroids: Map<string, [number, number]>,
  compare?: CompareOut,
  optimize?: OptimizeOut,
  districts?: ScenarioDistrict[],
): DistrictRow[] {
  const all = new Set(ids);
  for (const d of compare?.by_district ?? []) all.add(d.district_id);
  for (const c of optimize?.coverage ?? []) all.add(c.district_id);
  const flood = new Map((compare?.by_district ?? []).map((d) => [d.district_id, d]));
  const cov = new Map((optimize?.coverage ?? []).map((c) => [c.district_id, c]));
  const pop = new Map((districts ?? []).map((d) => [d.district_id, d.population]));
  const alloc = new Map<string, Record<string, number>>();
  for (const a of optimize?.allocation ?? []) {
    const r = alloc.get(a.district_id) ?? {};
    r[a.commodity_id] = (r[a.commodity_id] ?? 0) + a.quantity;
    alloc.set(a.district_id, r);
  }
  return [...all].sort().map((id) => {
    const f = flood.get(id);
    const c = cov.get(id);
    const p = pop.get(id) ?? null;
    return {
      id,
      floodedKm2: f?.flooded_km2 ?? null,
      floodedFraction: f?.flooded_fraction ?? null,
      population: p,
      allocation: alloc.get(id) ?? {},
      coverage: c?.fraction ?? null,
      access: c?.access_mode ?? null,
      unreached: c?.unreached_people ?? null,
      peopleCovered: c && p !== null ? Math.round(c.fraction * p) : null,
      centroid: centroids.get(id),
    };
  });
}

export const MAX_RADIUS_PX = 28;

/** Allocation circles: area proportional to people covered; the largest circle is MAX_RADIUS_PX. */
export function allocationFeatures(rows: DistrictRow[]) {
  const max = Math.max(0, ...rows.map((r) => r.peopleCovered ?? 0));
  const k = max > 0 ? MAX_RADIUS_PX / Math.sqrt(max) : 0;
  return {
    type: 'FeatureCollection' as const,
    features: rows
      .filter((r) => r.centroid && (r.peopleCovered ?? 0) > 0)
      .map((r) => ({
        type: 'Feature' as const,
        properties: { district_id: r.id, people_covered: r.peopleCovered ?? 0, k },
        geometry: { type: 'Point' as const, coordinates: r.centroid as [number, number] },
      })),
  };
}

export const EMPTY_FC = { type: 'FeatureCollection' as const, features: [] as unknown[] };

export function floodCollection(segment?: SegmentOut) {
  return segment?.extent_geojson ?? EMPTY_FC;
}

/** Collect every [lon, lat] pair of a GeoJSON geometry (Polygon or MultiPolygon). */
export function coordsOf(geometry: unknown): number[][] {
  const out: number[][] = [];
  const walk = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === 'number') out.push(c as number[]);
    else if (Array.isArray(c)) c.forEach(walk);
  };
  walk((geometry as { coordinates?: unknown } | null)?.coordinates);
  return out;
}
