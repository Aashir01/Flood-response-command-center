'use client';
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { Lang } from '@/api/types';
import { makeFmt, type Digits, type Fmt } from './format';
import { dirOf, makeT, type Dict, type TFn } from './t';

interface LangCtx {
  lang: Lang;
  dir: 'ltr' | 'rtl';
  dict: Dict;
  t: TFn;
  fmt: Fmt;
}
const Ctx = createContext<LangCtx | null>(null);

export function LangProvider({ lang, dict, digits = 'latn', children }: { lang: Lang; dict: Dict; digits?: Digits; children: ReactNode }) {
  const value = useMemo<LangCtx>(() => ({ lang, dir: dirOf(lang), dict, t: makeT(dict), fmt: makeFmt(lang, digits) }), [lang, dict, digits]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang(): LangCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useLang outside LangProvider');
  return v;
}
