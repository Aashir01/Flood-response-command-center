import { act, cleanup, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { OrganId } from '@/api/types';
import { CreatureSleeps } from '@/components/bench/CreatureSleeps';
import { LabBench } from '@/components/bench/LabBench';
import { OrganJar } from '@/components/bench/OrganJar';
import { ScenarioControl } from '@/components/bench/ScenarioControl';
import { benchReducer, initialState, reduceAll, type OrganState } from '@/state/benchReducer';
import en from '@/i18n/messages/en.json';
import { organs, stream } from '../helpers/fixtures';
import { benchValue, renderUi } from '../helpers/render';
import { BenchContext } from '@/state/BenchProvider';

afterEach(cleanup);

function LabBenchWith({ state }: { state: ReturnType<typeof initialState> }) {
  return (
    <BenchContext.Provider value={benchValue(state)}>
      <LabBench />
    </BenchContext.Provider>
  );
}
beforeAll(() => {
  // jsdom has no <dialog> modal API.
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  };
});

const ICON: Record<OrganState, string> = { idle: 'circle-dot', calling: 'bolt', done: 'check', unwell: 'warning', disabled: 'slash' };
const TEXT: Record<OrganState, string> = { idle: en['state.idle'], calling: en['state.calling'], done: en['state.done'], unwell: en['state.unwell'], disabled: en['state.disabled'] };

describe('OrganJar states (FRN-R2, FRN-R11.5)', () => {
  it.each(Object.keys(ICON) as OrganState[])('%s shows a distinct icon and text, not colour alone', (st) => {
    const view = { state: st, degraded: false, stub: false, note: st === 'unwell' ? 'Oracle did not answer within 8 s' : undefined };
    renderUi(<OrganJar organ="oracle" view={view} onOpen={() => {}} expanded={false} />, { fx: 'full' });
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('data-state', st);
    expect(within(btn).getByText(TEXT[st])).toBeInTheDocument();
    expect(btn.querySelector(`[data-icon="${ICON[st]}"]`)).not.toBeNull();
    if (st === 'unwell') expect(btn).toHaveAccessibleDescription(/did not answer/);
  });
});

describe('LabBench with the mock streams', () => {
  it('default-demo drives all four called organs to done; organ-error shows the organ is unwell with the reason', () => {
    const toEvents = (n: string) => stream(n).map((f) => ({ seq: f.seq, event: f.data }));
    const ok = reduceAll(toEvents('default-demo'), benchReducer(initialState(), { type: 'HEALTH', organs: organs().organs }));
    for (const o of ['eyes', 'oracle', 'library', 'ledger'] as OrganId[]) expect(ok.organs[o].state).toBe('done');
    const bad = reduceAll(toEvents('organ-error'));
    expect(bad.organs.oracle.state).toBe('unwell');
    renderUi(<LabBench />, { bench: benchValue(bad) });
    const jar = screen.getByRole('button', { name: /Oracle/ });
    expect(within(jar).getByText('The organ is unwell')).toBeInTheDocument();
    expect(jar).toHaveAccessibleDescription(/did not answer within 8 s/);
  });

  it('keyboard: Enter opens the drawer with the last call, Esc closes it and focus returns', async () => {
    const st = reduceAll(stream('default-demo').map((f) => ({ seq: f.seq, event: f.data })));
    renderUi(<LabBench />, { bench: benchValue(st) });
    const user = userEvent.setup();
    const jar = screen.getByRole('button', { name: /Eyes/ });
    jar.focus();
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog', { hidden: true });
    expect(within(dialog).getByText('Last call')).toBeInTheDocument();
    expect(within(dialog).getAllByText(/compare_with_permanent_water|segment_flood/).length).toBeGreaterThan(0);
    expect(within(dialog).getByLabelText('Raw summary')).toBeInTheDocument();
    act(() => {
      fireEvent(dialog, new Event('cancel', { cancelable: true }));
    });
    expect(dialog).not.toHaveAttribute('open');
    expect(jar).toHaveFocus();
  });

  it('a state change appears within one render of the event (FRN-R2.4, 200 ms budget)', () => {
    const ev = stream('default-demo')[1] as { seq: number; data: never };
    const { rerender } = renderUi(<LabBench />, { bench: benchValue(initialState()) });
    expect(screen.getByTestId('jar-status-eyes')).toHaveTextContent('Idle');
    const t0 = performance.now();
    const next = benchReducer(initialState(), { type: 'EVENT', seq: ev.seq, event: ev.data });
    rerender(<LabBenchWith state={next} />);
    expect(screen.getByTestId('jar-status-eyes')).toHaveTextContent('Calling…');
    expect(performance.now() - t0).toBeLessThan(200);
  });
});

describe('ScenarioControl (FRN-R3)', () => {
  it('defaults to Sindh Aug 2022 demo; Run calls start in demo mode', async () => {
    const start = vi.fn(async () => {});
    renderUi(<ScenarioControl />, { bench: benchValue({}, { start }) });
    expect(screen.getByRole('combobox', { name: 'Region' })).toHaveDisplayValue('Sindh, Pakistan');
    expect(screen.getByRole('combobox', { name: 'Scenario' })).toHaveDisplayValue('Sindh floods, Aug 2022 (demo)');
    await userEvent.setup().click(screen.getByTestId('run'));
    expect(start).toHaveBeenCalledWith({ region: 'pk-sindh', scenario: 'demo-sindh-2022', mode: 'demo' });
  });
  it('while running: Run is aria-disabled, Cancel is offered, controls are locked', async () => {
    const cancel = vi.fn(async () => {});
    const st = { ...initialState(), run: { status: 'running' as const } };
    renderUi(<ScenarioControl />, { bench: benchValue(st, { cancel }) });
    expect(screen.getByTestId('run')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('combobox', { name: 'Region' })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cancel' }));
    expect(cancel).toHaveBeenCalled();
  });
  it('live is unavailable when the Brain reports no live source', () => {
    renderUi(<ScenarioControl />, { bench: benchValue({}, { health: { ...organs(), live_available: false } }) });
    expect(screen.getByRole('switch')).toBeDisabled();
    expect(screen.getByText(/Live mode is unavailable/)).toBeInTheDocument();
  });
});

describe('CreatureSleeps (FRN-R10.2)', () => {
  it('offers a retry that calls health', async () => {
    const retryHealth = vi.fn(async () => false);
    renderUi(<CreatureSleeps />, { bench: benchValue({}, { retryHealth, healthStatus: 'failed' }) });
    expect(screen.getByRole('heading', { name: 'The creature sleeps' })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try to wake it' }));
    expect(retryHealth).toHaveBeenCalled();
  });
});
