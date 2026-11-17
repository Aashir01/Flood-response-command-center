// Sound recipes as pure node-graph descriptions (design section 14). The engine interprets them; tests read
// them directly. All sounds are synthesized; there are no audio files.
export type SoundId = 'hum' | 'thunder' | 'twitch' | 'unwell' | 'done';

export type Source =
  | { kind: 'osc'; type: OscillatorType; freq: number; freqTo?: number; glideS?: number; detune?: number }
  | { kind: 'noise'; seconds: number };
export interface Filter {
  type: BiquadFilterType;
  freq: number;
  freqTo?: number;
  sweepS?: number;
  q?: number;
  lfo?: { rateHz: number; depthHz: number };
}
export interface Envelope {
  attackS: number;
  decayS: number;
  peak: number;
  /** Loop until stopped (ambient). */
  sustain?: boolean;
}
export interface Recipe {
  id: SoundId;
  sources: Source[];
  filter?: Filter;
  env: Envelope;
}

export const MASTER_GAIN = 0.3;

export const RECIPES: Record<SoundId, Recipe> = {
  hum: {
    id: 'hum',
    sources: [
      { kind: 'osc', type: 'sawtooth', freq: 50 },
      { kind: 'osc', type: 'sawtooth', freq: 50.7 },
    ],
    filter: { type: 'lowpass', freq: 120, lfo: { rateHz: 0.1, depthHz: 30 } },
    env: { attackS: 0.8, decayS: 0.8, peak: 0.03, sustain: true },
  },
  thunder: {
    id: 'thunder',
    sources: [{ kind: 'noise', seconds: 1.8 }],
    filter: { type: 'lowpass', freq: 900, freqTo: 80, sweepS: 1.8 },
    env: { attackS: 0.02, decayS: 1.6, peak: 0.35 },
  },
  twitch: {
    id: 'twitch',
    sources: [{ kind: 'noise', seconds: 0.03 }],
    filter: { type: 'bandpass', freq: 1200, q: 4 },
    env: { attackS: 0.002, decayS: 0.028, peak: 0.05 },
  },
  unwell: {
    id: 'unwell',
    sources: [{ kind: 'osc', type: 'sine', freq: 220, freqTo: 140, glideS: 0.4 }],
    env: { attackS: 0.02, decayS: 0.38, peak: 0.06 },
  },
  done: {
    id: 'done',
    sources: [{ kind: 'osc', type: 'sine', freq: 440 }],
    env: { attackS: 0.005, decayS: 0.115, peak: 0.04 },
  },
};

/** Total audible length of a one-shot recipe, seconds. */
export function recipeLength(r: Recipe): number {
  return r.env.attackS + r.env.decayS;
}
