// Tolerant Web Storage access: private mode, disabled storage and SSR all degrade to "no value".
export const KEYS = {
  sound: 'stitch.sound',
  contrast: 'stitch.contrast',
  digits: 'stitch.digits',
  run: 'stitch.run',
  ttsConsent: 'stitch.tts-consent',
  awakened: 'stitch.awakened',
} as const;

function store(kind: 'local' | 'session'): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readPref(key: string, kind: 'local' | 'session' = 'local'): string | null {
  try {
    return store(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string | null, kind: 'local' | 'session' = 'local'): void {
  try {
    const s = store(kind);
    if (!s) return;
    if (value === null) s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    /* quota or disabled */
  }
}

export function readJson<T>(key: string, kind: 'local' | 'session' = 'local'): T | null {
  const raw = readPref(key, kind);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}
