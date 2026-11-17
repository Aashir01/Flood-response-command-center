'use client';
import type { ReactNode } from 'react';
import { SkipLinks } from '@/a11y/SkipLinks';
import { DecisionSupportNotice } from '@/components/shell/Banners';
import { Footer, Header, type Route } from '@/components/shell/Header';
import { EvalHeartbeat } from '@/components/evals/EvalHeartbeat';

/** Shell for the evals and about routes. */
export function SimpleScreen({ route, children }: { route: Route; children: ReactNode }) {
  return (
    <>
      <SkipLinks links={[{ href: '#main', key: 'skip.main' }]} />
      <Header route={route} />
      <div className="banner-stack">
        <DecisionSupportNotice />
      </div>
      <main className="page" id="main" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </>
  );
}

export function EvalsScreen() {
  return (
    <SimpleScreen route="evals/">
      <EvalHeartbeat />
    </SimpleScreen>
  );
}
