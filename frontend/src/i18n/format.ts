// Number and date formatting. Western digits by default; Urdu (extended Arabic-Indic, U+06F0..U+06F9) on request.
// Numbers inside Brain claim text are shown unchanged; only numbers the UI renders itself pass through here.
import type { Lang } from '@/api/types';

export type Digits = 'latn' | 'arabext';

export function localeOf(lang: Lang, digits: Digits = 'latn'): string {
  if (lang === 'ur') return digits === 'arabext' ? 'ur-PK-u-nu-arabext' : 'ur-PK-u-nu-latn';
  return 'en-GB-u-nu-latn';
}

const cache = new Map<string, Intl.NumberFormat>();
function nf(locale: string, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(opts)}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale, opts);
    cache.set(key, f);
  }
  return f;
}

export interface Fmt {
  lang: Lang;
  digits: Digits;
  num: (n: number | null | undefined, maxFrac?: number) => string;
  int: (n: number | null | undefined) => string;
  pct: (fraction: number | null | undefined, maxFrac?: number) => string;
  compact: (n: number | null | undefined) => string;
  date: (iso: string | null | undefined) => string;
  dateTime: (iso: string | null | undefined) => string;
  sig: (n: number | null | undefined, digits?: number) => string;
}

export function makeFmt(lang: Lang, digits: Digits = 'latn'): Fmt {
  const loc = localeOf(lang, digits);
  const dash = '–';
  const ok = (n: number | null | undefined): n is number => typeof n === 'number' && Number.isFinite(n);
  return {
    lang,
    digits,
    num: (n, maxFrac = 1) => (ok(n) ? nf(loc, { maximumFractionDigits: maxFrac }).format(n) : dash),
    int: (n) => (ok(n) ? nf(loc, { maximumFractionDigits: 0 }).format(n) : dash),
    pct: (f, maxFrac = 0) => (ok(f) ? nf(loc, { style: 'percent', maximumFractionDigits: maxFrac }).format(f) : dash),
    compact: (n) => (ok(n) ? nf(loc, { notation: 'compact', maximumFractionDigits: 1 }).format(n) : dash),
    sig: (n, d = 2) => (ok(n) ? nf(loc, { maximumSignificantDigits: d }).format(n) : dash),
    date: (iso) => {
      if (!iso) return dash;
      const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
      return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(d);
    },
    dateTime: (iso) => {
      if (!iso) return dash;
      const d = new Date(iso);
      return Number.isNaN(d.getTime())
        ? iso
        : new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' }).format(d);
    },
  };
}
