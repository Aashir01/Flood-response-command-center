'use client';
// Voice (FRN-R6, R14.4, R15.2): play the spoken briefing on a click only (never autoplay), disclose the hosted
// provider before the first synthesis, show who produced the audio. Disabled, not broken, when Voice is cut.
import { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { VoiceSpeakResponse } from '@/api/types';
import { IconPlay, IconSlash, IconSound, IconWarning } from '@/components/icons';
import { Drawer } from '@/components/shell/Drawer';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { KEYS, readJson, writePref } from '@/lib/storage';
import { useBench } from '@/state/BenchProvider';
import { useVoiceInfo } from '@/voice/useVoice';
import { base64ToBlob } from '@/voice/wav';
import { Waveform } from './Waveform';

function consented(provider: string): boolean {
  return (readJson<string[]>(KEYS.ttsConsent) ?? []).includes(provider);
}
function storeConsent(provider: string) {
  const list = readJson<string[]>(KEYS.ttsConsent) ?? [];
  if (!list.includes(provider)) writePref(KEYS.ttsConsent, JSON.stringify([...list, provider]));
}

export function VoiceControls() {
  const { t, lang } = useLang();
  const { state } = useBench();
  const voice = useVoiceInfo();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<VoiceSpeakResponse | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [disclose, setDisclose] = useState(false);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const briefingId = state.briefing?.briefing_id;

  useEffect(() => () => void (src && URL.revokeObjectURL(src)), [src]);

  const synthesize = async () => {
    if (!briefingId) return;
    setBusy(true);
    setErr(null);
    // Routing through an analyser needs an AudioContext; create it inside the click (user gesture).
    if (!ctxRef.current && typeof AudioContext !== 'undefined') ctxRef.current = new AudioContext();
    const r = await api.speak({ briefing_id: briefingId, lang: state.briefing?.lang ?? lang } as never);
    setBusy(false);
    if (!r.ok) {
      setErr(`${r.error.code}: ${r.error.message}`);
      return;
    }
    setResult(r.value);
    const url = URL.createObjectURL(base64ToBlob(r.value.audio_b64, r.value.format === 'mp3' ? 'audio/mpeg' : 'audio/wav'));
    setSrc(url);
    requestAnimationFrame(() => {
      const el = audioRef.current;
      if (!el) return;
      const ctx = ctxRef.current;
      if (ctx && !analyser) {
        try {
          const node = ctx.createMediaElementSource(el);
          const an = ctx.createAnalyser();
          an.fftSize = 1024;
          node.connect(an).connect(ctx.destination);
          setAnalyser(an);
        } catch {
          /* already connected */
        }
      }
      void el.play().catch(() => {
        /* the controls stay visible; the user can press play */
      });
    });
  };

  const onPlay = () => {
    if (voice.hosted && !consented(voice.provider)) {
      setDisclose(true);
      return;
    }
    void synthesize();
  };

  if (voice.status === 'disabled' || voice.status === 'unwell') {
    return (
      <section className="panel voice" aria-labelledby="voice-title" data-testid="voice-controls" data-voice={voice.status}>
        <div className="panel__head">
          <IconSound className="panel__icon" aria-hidden="true" />
          <h2 id="voice-title">{t('voice.title')}</h2>
          <span className="spacer chip chip--demo">
            {voice.status === 'disabled' ? <IconSlash /> : <IconWarning />}
            {t(voice.status === 'disabled' ? 'state.disabled' : 'state.unwell')}
          </span>
        </div>
        <p className="small">{t(voice.status === 'disabled' ? 'voice.disabled' : 'voice.unwell')}</p>
        <div>
          <button type="button" className="btn" disabled aria-describedby="voice-title">
            <IconPlay />
            {t('voice.play')}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="panel voice" aria-labelledby="voice-title" data-testid="voice-controls" data-voice={voice.status}>
      <div className="panel__head">
        <IconSound className="panel__icon" aria-hidden="true" on />
        <h2 id="voice-title">{t('voice.title')}</h2>
      </div>
      {!briefingId ? <p className="small muted">{t('voice.needBriefing')}</p> : null}
      <div className="ask-row">
        <button type="button" className="btn" onClick={onPlay} aria-disabled={!briefingId || busy} disabled={!briefingId} data-testid="voice-play">
          <IconPlay />
          {busy ? t('voice.preparing') : t('voice.play')}
        </button>
      </div>
      {err ? (
        <p className="state state--error small" role="alert">
          {t('voice.error', { reason: err })}
        </p>
      ) : null}
      {src ? (
        <>
          <Waveform analyser={analyser} label={t('voice.waveform')} />
          <audio ref={audioRef} src={src} controls preload="auto" style={{ inlineSize: '100%' }} data-testid="voice-audio" />
        </>
      ) : null}
      {result ? (
        <p className="small muted" data-testid="voice-provider">
          {t('voice.by', { provider: result.provider, how: t(`voice.how.${result.synthesized}` as MessageKey) })}
          {result.voice ? ` · ${result.voice}` : ''}
        </p>
      ) : null}
      <Drawer open={disclose} onClose={() => setDisclose(false)} title={t('voice.disclosure.title')} className="modal">
        <p>{t('voice.disclosure.body', { provider: voice.provider })}</p>
        <div className="ask-row">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              storeConsent(voice.provider);
              setDisclose(false);
              void synthesize();
            }}
          >
            {t('voice.disclosure.accept')}
          </button>
          <button type="button" className="btn" onClick={() => setDisclose(false)}>
            {t('voice.disclosure.decline')}
          </button>
        </div>
      </Drawer>
    </section>
  );
}
