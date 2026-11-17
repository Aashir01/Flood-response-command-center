'use client';
import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { ORGAN_IDS } from '@/api/types';
import { IconBolt, IconInfo, IconStop, IconWarning } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { DEFAULT_REGION, DEFAULT_SCENARIO, REGIONS } from '@/lib/scenarios';
import { useBench } from '@/state/BenchProvider';
import { STATE_KEY, StatusIcon } from './StatusIcon';

function subscribeOnline(cb: () => void) {
  window.addEventListener('online', cb);
  window.addEventListener('offline', cb);
  return () => {
    window.removeEventListener('online', cb);
    window.removeEventListener('offline', cb);
  };
}
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
}

export function ScenarioControl() {
  const { t, fmt } = useLang();
  const { state, start, cancel, resume, stream, reconnectAttempt, health } = useBench();
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [live, setLive] = useState(false);
  const online = useOnline();
  const ids = useId();
  const running = state.run.status === 'starting' || state.run.status === 'running';
  const liveBlocked = !online ? t('control.liveReasonOffline') : health && health.live_available === false ? t('control.liveReasonBrain') : null;
  const scenarios = REGIONS.find((r) => r.id === region)?.scenarios ?? [];

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- live cannot stay on once it is unavailable
    if (liveBlocked && live) setLive(false);
  }, [liveBlocked, live]);

  const run = () => {
    if (running) return;
    void start({ region, scenario, mode: live && !liveBlocked ? 'live' : 'demo' });
  };
  const failure = state.run.status === 'failed' ? state.errors.find((e) => e.fatal && !e.organ) : undefined;

  return (
    <section className="panel control" aria-labelledby="control-title" id="control">
      <div className="panel__head">
        <IconBolt className="panel__icon" aria-hidden="true" />
        <h2 id="control-title">{t('control.title')}</h2>
      </div>
      <div className="control__row">
        <div className="field">
          <label htmlFor={`${ids}-region`}>{t('control.region')}</label>
          <select id={`${ids}-region`} className="select" value={region} disabled={running} onChange={(e) => setRegion(e.target.value)}>
            {REGIONS.map((r) => (
              <option key={r.id} value={r.id}>
                {t(`region.${r.id}` as MessageKey)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${ids}-scenario`}>{t('control.scenario')}</label>
          <select id={`${ids}-scenario`} className="select" value={scenario} disabled={running} onChange={(e) => setScenario(e.target.value)}>
            {scenarios.map((s) => (
              <option key={s} value={s}>
                {t(`scenario.${s}` as MessageKey)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="switch">
        <button
          type="button"
          role="switch"
          id={`${ids}-live`}
          aria-checked={live}
          aria-describedby={`${ids}-live-help`}
          disabled={running || liveBlocked !== null}
          onClick={() => setLive((v) => !v)}
        />
        <label htmlFor={`${ids}-live`}>{t('control.live')}</label>
      </div>
      <p id={`${ids}-live-help`} className="small muted">
        {liveBlocked ? t('control.liveUnavailable', { reason: liveBlocked }) : t('control.liveHelp')}
      </p>
      <div className="control__actions">
        <button
          type="button"
          className="btn btn--primary"
          aria-disabled={running}
          aria-describedby={running ? `${ids}-run-why` : undefined}
          onClick={run}
          data-testid="run"
        >
          <IconBolt />
          {running ? t('control.running') : t('control.run')}
        </button>
        {running ? (
          <button type="button" className="btn btn--danger" onClick={() => void cancel()}>
            <IconStop />
            {t('control.cancel')}
          </button>
        ) : null}
        {running ? (
          <span id={`${ids}-run-why`} className="sr-only">
            {t('control.runDisabled')}
          </span>
        ) : null}
      </div>

      {stream === 'reconnecting' ? (
        <p className="state state--partial small" role="status">
          {t('control.reconnecting', { n: reconnectAttempt })}
        </p>
      ) : null}
      {state.run.status === 'disconnected' ? (
        <div className="state state--error" role="alert">
          <p className="state__title">
            <IconWarning />
            {t('control.lost')}
          </p>
          <div>
            <button type="button" className="btn btn--small" onClick={resume}>
              {t('control.resume')}
            </button>
          </div>
        </div>
      ) : null}
      {state.run.status === 'cancelled' ? (
        <p className="state small" role="status">
          <span className="state__title">
            <IconInfo />
            {t('control.cancelled')}
          </span>
        </p>
      ) : null}
      {failure ? (
        <div className="state state--error" role="alert">
          <p className="state__title">
            <IconWarning />
            {t('control.failed', { reason: `${failure.code}: ${failure.message}` })}
          </p>
          <div>
            <button type="button" className="btn btn--small" onClick={run}>
              {t('common.retry')}
            </button>
          </div>
        </div>
      ) : null}

      {state.run.status !== 'idle' ? (
        <div>
          <h3 className="small muted" id={`${ids}-progress`}>
            {t('control.progress')}
          </h3>
          <ul className="progress" aria-labelledby={`${ids}-progress`}>
            {ORGAN_IDS.map((o) => {
              const v = state.organs[o];
              const label = v.state === 'idle' && v.note === 'queued' ? t('state.queued') : t(STATE_KEY[v.state]);
              return (
                <li key={o} data-state={v.state}>
                  <StatusIcon state={v.state} />
                  <span>
                    {t(`organ.${o}` as MessageKey)}: {label}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {state.run.status === 'completed' && state.run.endedAt ? (
        <p className="small muted">
          {t('control.lastRun', { time: fmt.dateTime(state.run.endedAt) })}
        </p>
      ) : null}
    </section>
  );
}
