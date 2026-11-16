export type Fx = 'full' | 'lite' | 'none';

export interface FxProbe {
  reducedMotion: boolean;
  hardwareConcurrency?: number;
  deviceMemory?: number;
  avgFps?: number;
}

/** Chosen once per session (design §5.4). */
export function chooseFx(p: FxProbe): Fx {
  if (p.reducedMotion) return 'none';
  if ((p.hardwareConcurrency ?? 8) <= 2 || (p.deviceMemory ?? 8) <= 2 || (p.avgFps !== undefined && p.avgFps < 40)) return 'lite';
  return 'full';
}