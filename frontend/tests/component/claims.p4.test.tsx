// FRN-P4: no briefing claim renders without an accessible evidence control.
import { cleanup, screen } from '@testing-library/react';
import fc from 'fast-check';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Claim } from '@/api/types';
import { ClaimItem } from '@/components/briefing/ClaimItem';
import { FC_RUNS } from '../helpers/arb';
import { renderUi } from '../helpers/render';

afterEach(cleanup);

const refArb = fc.record({
  run_id: fc.uuid(),
  organ: fc.constantFrom('eyes', 'oracle', 'library', 'ledger', 'brain'),
  tool: fc.constantFrom('segment_flood', 'forecast_river', 'answer_with_citations', 'optimize_allocation'),
  json_pointer: fc.constantFrom('/data/a', '/data/forecast/0/discharge/p50', '/data/citations/0'),
});
const claimArb = fc.record({
  id: fc.string({ minLength: 1, maxLength: 12 }).map((s) => `c.${s}`),
  kind: fc.constantFrom('number', 'statement', 'recommendation'),
  text: fc.string({ minLength: 1, maxLength: 160 }).filter((s) => s.trim().length > 0),
  evidence: fc.array(refArb, { minLength: 1, maxLength: 3 }),
}) as fc.Arbitrary<Claim>;

describe('FRN-P4 claims always carry an evidence control', () => {
  it('every generated claim list renders one named evidence button per claim', () => {
    fc.assert(
      fc.property(fc.uniqueArray(claimArb, { minLength: 1, maxLength: 6, selector: (c) => c.id }), (claims) => {
        const { unmount, container } = renderUi(
          <ul>
            {claims.map((c) => (
              <ClaimItem key={c.id} claim={c} lang="en" />
            ))}
          </ul>,
        );
        const items = container.querySelectorAll('[data-claim-id]');
        expect(items).toHaveLength(claims.length);
        items.forEach((li, i) => {
          const btn = li.querySelector('button[data-testid="evidence-button"]');
          expect(btn).not.toBeNull();
          const name = btn?.getAttribute('aria-label') ?? '';
          expect(name).toContain(`(${claims[i]?.evidence.length})`);
          expect(name.length).toBeGreaterThan(10);
        });
        unmount();
      }),
      { numRuns: Math.min(FC_RUNS, 60) },
    );
  });

  it('a claim without evidence cannot render (throws in test mode)', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderUi(<ClaimItem claim={{ id: 'bad', kind: 'statement', text: 'unsupported', evidence: [] } as Claim} lang="en" />)).toThrow(/FRN-P4/);
    spy.mockRestore();
  });

  it('the evidence button is reachable by role and name', () => {
    renderUi(<ClaimItem claim={{ id: 'x', kind: 'number', text: 'Flood covers 10 km2', evidence: [{ run_id: 'r', organ: 'eyes', tool: 'segment_flood', json_pointer: '/data/x' }] } as Claim} lang="en" />);
    expect(screen.getByRole('button', { name: /Evidence \(1\) for: Flood covers 10 km2/ })).toBeInTheDocument();
  });
});
