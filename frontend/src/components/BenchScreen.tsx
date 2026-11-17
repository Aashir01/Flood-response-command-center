'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ORGAN_IDS, type Lang, type OrganId } from '@/api/types';
import { LiveRegion } from '@/a11y/LiveRegion';
import { SkipLinks } from '@/a11y/SkipLinks';
import { AskTheCreature } from '@/components/ask/AskTheCreature';
import { LightningAwakening } from '@/components/awakening/LightningAwakening';
import { CreatureSleeps } from '@/components/bench/CreatureSleeps';
import { LabBench } from '@/components/bench/LabBench';
import { ScenarioControl, useOnline } from '@/components/bench/ScenarioControl';
import { EvidenceProvider } from '@/components/briefing/EvidenceContext';
import { VitalSignsBriefing } from '@/components/briefing/VitalSignsBriefing';
import { MapSection } from '@/components/map/MapSection';
import { DecisionSupportNotice, DemoNotice, OfflineBanner } from '@/components/shell/Banners';
import { Footer, Header } from '@/components/shell/Header';
import { VoiceControls } from '@/components/voice/VoiceControls';
import type { AwakeningKind } from '@/motion/awakening';
import { useSound } from '@/sound/SoundProvider';
import { BenchProvider, useBench } from '@/state/BenchProvider';
import type { OrganState } from '@/state/benchReducer';

function useOrganSounds() {
  const { state } = useBench();
  const { play } = useSound();
  const prev = useRef<Record<OrganId, OrganState> | null>(null);
  useEffect(() => {
    const cur = Object.fromEntries(ORGAN_IDS.map((o) => [o, state.organs[o].state])) as Record<OrganId, OrganState>;
    const p = prev.current;
    prev.current = cur;
    if (!p) return;
    for (const o of ORGAN_IDS) {
      if (p[o] === cur[o]) continue;
      if (cur[o] === 'calling') play('twitch');
      else if (cur[o] === 'done') play('done');
      else if (cur[o] === 'unwell') play('unwell');
    }
  }, [state.organs, play]);
}

function Screen() {
  const { state, healthStatus, health, completions, lastRequest } = useBench();
  const { play } = useSound();
  const online = useOnline();
  const [awaken, setAwaken] = useState<{ kind: AwakeningKind; key: number } | null>({ kind: 'boot', key: 0 });
  useOrganSounds();

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a finished live run plays the short awakening
    if (completions > 0) setAwaken({ kind: 'complete', key: completions });
  }, [completions]);
  const onDone = useCallback(() => setAwaken(null), []);
  const onThunder = useCallback(() => play('thunder'), [play]);

  const b = state.briefing;
  const mode = b?.mode ?? 'demo';
  const fellBack = state.notices.some((n) => n.code === 'MODE_FALLBACK') || (b?.mode === 'demo' && lastRequest?.mode === 'live');
  const asleep = healthStatus === 'failed';

  return (
    <>
      <LightningAwakening play={awaken} onDone={onDone} onThunder={onThunder} />
      <SkipLinks
        links={[
          { href: '#bench', key: 'skip.bench' },
          { href: '#briefing', key: 'skip.briefing' },
          { href: '#ask', key: 'skip.ask' },
        ]}
      />
      <LiveRegion announcements={state.announcements} />
      <Header route="" mode={mode} />
      <div className="banner-stack">
        <DecisionSupportNotice />
        {!online || fellBack ? <OfflineBanner reason={fellBack ? 'fallback' : 'offline'} /> : null}
        {mode === 'demo' ? <DemoNotice /> : null}
      </div>
      <main className="page" id="main">
        {asleep ? (
          <div id="bench" tabIndex={-1}>
            <CreatureSleeps />
          </div>
        ) : (
          <>
            <div className="page-top">
              <ScenarioControl />
              <LabBench />
            </div>
            <div className="page-main">
              <MapSection />
              <VitalSignsBriefing />
            </div>
            <div className="page-top" style={{ gridTemplateColumns: undefined }}>
              <VoiceControls />
              <AskTheCreature />
            </div>
          </>
        )}
      </main>
      <Footer contract={health?.contract_version} brain={health?.brain_version} />
    </>
  );
}

export function BenchScreen({ lang }: { lang: Lang }) {
  return (
    <BenchProvider lang={lang}>
      <EvidenceProvider>
        <Screen />
      </EvidenceProvider>
    </BenchProvider>
  );
}
