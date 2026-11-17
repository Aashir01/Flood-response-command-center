import type en from './messages/en.json';
import type { Lang } from '@/api/types';

export type MessageKey = keyof typeof en;
export type Dict = Record<MessageKey, string>;
export type Params = Record<string, string | number>;
export type TFn = (key: MessageKey, params?: Params) => string;

export const LANGS: readonly Lang[] = ['en', 'ur'] as const;
export const isLang = (x: unknown): x is Lang => x === 'en' || x === 'ur';
export const dirOf = (l: Lang): 'ltr' | 'rtl' => (l === 'ur' ? 'rtl' : 'ltr');

/** Placeholder names in a message, e.g. "{organ} is {state}" -> ["organ", "state"]. */
export function placeholders(msg: string): string[] {
  return [...msg.matchAll(/\{(\w+)\}/g)].map((m) => m[1] as string).sort();
}

export function interpolate(msg: string, params?: Params): string {
  if (!params) return msg;
  return msg.replace(/\{(\w+)\}/g, (all, k: string) => (k in params ? String(params[k]) : all));
}

export function makeT(dict: Dict): TFn {
  return (key, params) => interpolate(dict[key] ?? key, params);
}

/** Has a key? (for dynamic keys built from data, e.g. `refusal.title.${reason}`). */
export function hasKey(dict: Dict, key: string): key is MessageKey {
  return Object.prototype.hasOwnProperty.call(dict, key);
}
