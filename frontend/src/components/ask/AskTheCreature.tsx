'use client';
// Ask the creature (FRN-R16): one text box to POST /ask, rendered like the briefing's guidance.
import { useId, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { ApiError, AskResponse, Claim } from '@/api/types';
import { ClaimItem } from '@/components/briefing/ClaimItem';
import { RefusalCard } from '@/components/briefing/RefusalCard';
import { LabelChip } from '@/components/briefing/labels';
import { IconMic, IconStop, IconWarning } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import type { RecorderHandle, RecordError } from '@/voice/recorder';
import { useVoiceInfo } from '@/voice/useVoice';
import { MAX_RECORD_S } from '@/voice/wav';
import { Waveform } from '@/components/voice/Waveform';

export const MAX_QUESTION = 500;

type View = { k: 'idle' } | { k: 'loading' } | { k: 'done'; res: AskResponse } | { k: 'error'; err: ApiError };

const MIC_ERR: Record<RecordError, 'voice.micDenied' | 'voice.micMissing' | 'voice.micInsecure'> = {
  denied: 'voice.micDenied',
  missing: 'voice.micMissing',
  insecure: 'voice.micInsecure',
  unsupported: 'voice.micInsecure',
  failed: 'voice.micMissing',
};

export function AskTheCreature() {
  const { t, fmt } = useLang();
  const voice = useVoiceInfo();
  const ids = useId();
  const [q, setQ] = useState('');
  const [view, setView] = useState<View>({ k: 'idle' });
  const [rec, setRec] = useState<{ handle: RecorderHandle; seconds: number } | null>(null);
  const [micMsg, setMicMsg] = useState<string | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const tooLong = q.length > MAX_QUESTION;
  const empty = q.trim().length === 0;

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (tooLong || empty || view.k === 'loading') return;
    setView({ k: 'loading' });
    const r = await api.ask(q.trim(), 'auto');
    setView(r.ok ? { k: 'done', res: r.value } : { k: 'error', err: r.error });
  };

  const stopRec = async (handle: RecorderHandle) => {
    setRec(null);
    setTranscribing(true);
    const out = await handle.stop();
    const r = await api.transcribe(out.b64, out.format, 'auto');
    setTranscribing(false);
    if (r.ok) {
      setQ(r.value.text.slice(0, MAX_QUESTION)); // fills the box; never auto-submits
      setMicMsg(t('ask.transcribed'));
      area.current?.focus();
    } else setMicMsg(t('voice.error', { reason: `${r.error.code}: ${r.error.message}` }));
  };

  const toggleMic = async () => {
    if (rec) return stopRec(rec.handle);
    setMicMsg(null);
    try {
      const { startRecording } = await import('@/voice/recorder');
      let handle: RecorderHandle | null = null;
      handle = await startRecording(
        (s) => setRec((cur) => (cur ? { ...cur, seconds: s } : cur)),
        () => handle && void stopRec(handle),
      );
      setRec({ handle, seconds: 0 });
    } catch (e) {
      const kind = ((e as { kind?: RecordError }).kind ?? 'failed') as RecordError;
      setMicMsg(t(MIC_ERR[kind]));
      area.current?.focus();
    }
  };

  const res = view.k === 'done' ? view.res : null;
  const data = res?.result?.data as { citations?: { doc_id: string; page: number; publisher: string; title: string }[]; refusal?: { reason?: string; closest_hits?: never[] } | null } | undefined;
  const claimLang = (res?.claims[0]?.text ?? q).match(/[\u0600-\u06FF]/) ? 'ur' : 'en';

  return (
    <section className="panel" aria-labelledby={`${ids}-title`} id="ask" tabIndex={-1} data-testid="ask">
      <div className="panel__head">
        <svg className="panel__icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M4 5h16v11H9l-5 4V5Z" />
          <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5M12 15h.01" />
        </svg>
        <h2 id={`${ids}-title`}>{t('ask.title')}</h2>
      </div>
      <form className="ask-form" onSubmit={submit} noValidate>
        <label htmlFor={`${ids}-q`}>{t('ask.label')}</label>
        <textarea
          id={`${ids}-q`}
          ref={area}
          className="textarea"
          dir="auto"
          value={q}
          placeholder={t('ask.placeholder')}
          aria-describedby={`${ids}-count${tooLong ? ` ${ids}-long` : ''}`}
          aria-invalid={tooLong}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void submit();
          }}
          data-testid="ask-input"
        />
        <div className="ask-row">
          <span id={`${ids}-count`} className="small muted counter" data-over={tooLong}>
            {t('ask.counter', { n: fmt.int(q.length), max: fmt.int(MAX_QUESTION) })}
          </span>
          <span style={{ marginInlineStart: 'auto' }} />
          {voice.canTranscribe ? (
            <button type="button" className="btn" onClick={() => void toggleMic()} aria-pressed={rec !== null} disabled={transcribing} data-testid="ask-mic">
              {rec ? <IconStop /> : <IconMic />}
              {rec ? t('ask.micStop') : t('ask.mic')}
            </button>
          ) : null}
          <button type="submit" className="btn btn--primary" aria-disabled={tooLong || empty || view.k === 'loading'} data-testid="ask-submit">
            {view.k === 'loading' ? t('ask.asking') : t('ask.submit')}
          </button>
        </div>
        {tooLong ? (
          <p id={`${ids}-long`} className="small danger-text" role="alert">
            {t('ask.tooLong', { max: MAX_QUESTION })}
          </p>
        ) : null}
        {rec ? (
          <div role="status" className="small" style={{ display: 'grid', gap: 6 }}>
            <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
              <span className="rec-dot" aria-hidden="true" />
              {t('voice.recording', { s: fmt.int(rec.seconds), max: MAX_RECORD_S })}
            </span>
            <Waveform analyser={rec.handle.analyser} label={t('voice.waveform')} />
          </div>
        ) : null}
        {transcribing ? (
          <p role="status" className="small muted">
            {t('voice.transcribing')}
          </p>
        ) : null}
        {micMsg ? (
          <p role="status" className="small">
            {micMsg}
          </p>
        ) : null}
      </form>

      <div aria-live="polite" className="answer">
        {view.k === 'loading' ? (
          <p className="small muted" role="status">
            {t('ask.asking')}
          </p>
        ) : null}
        {view.k === 'error' ? (
          <div className="state state--error" role="alert" data-testid="ask-error">
            <p className="state__title">
              <IconWarning />
              {view.err.code === 'RATE_LIMITED'
                ? t('ask.rateLimited', { s: view.err.retryAfterS ?? 10 })
                : t('ask.error', { reason: `${view.err.code}: ${view.err.message}` })}
            </p>
            {view.err.code !== 'RATE_LIMITED' ? (
              <div>
                <button type="button" className="btn btn--small" onClick={() => void submit()}>
                  {t('common.retry')}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
        {res ? (
          <>
            <div className="chips">
              <LabelChip label={res.mode} />
              {res.status === 'refused' ? <LabelChip label="refusal" /> : <span className="chip chip--validated">{t('ask.answered')}</span>}
            </div>
            {res.status === 'answered' ? (
              <ul className="claims" data-testid="ask-answer">
                {res.claims.map((c: Claim) => (
                  <ClaimItem
                    key={c.id}
                    claim={c}
                    lang={claimLang}
                    extra={
                      data?.citations?.length ? (
                        <span className="chips">
                          {data.citations.map((ci) => (
                            <span className="cite" key={`${ci.doc_id}-${ci.page}`}>
                              <Bdi>
                                {ci.publisher} · {t('guidance.page', { page: ci.page })}
                              </Bdi>
                            </span>
                          ))}
                        </span>
                      ) : null
                    }
                  />
                ))}
              </ul>
            ) : (
              <RefusalCard refusal={data?.refusal ?? { reason: 'INSUFFICIENT_EVIDENCE' }}>
                {res.refusal_claim ? (
                  <ul className="claims">
                    <ClaimItem claim={res.refusal_claim} lang={claimLang} />
                  </ul>
                ) : null}
              </RefusalCard>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
