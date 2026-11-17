import { IconBolt, IconCheck, IconIdle, IconSlash, IconWarning } from '@/components/icons';
import type { OrganState } from '@/state/benchReducer';

/** One distinct shape per state: idle circle-dot, calling bolt, done check, unwell triangle, disabled slash. */
export function StatusIcon({ state }: { state: OrganState }) {
  switch (state) {
    case 'calling':
      return <IconBolt data-icon="bolt" />;
    case 'done':
      return <IconCheck data-icon="check" />;
    case 'unwell':
      return <IconWarning data-icon="warning" />;
    case 'disabled':
      return <IconSlash data-icon="slash" />;
    default:
      return <IconIdle data-icon="circle-dot" />;
  }
}

export const STATE_KEY = {
  idle: 'state.idle',
  calling: 'state.calling',
  done: 'state.done',
  unwell: 'state.unwell',
  disabled: 'state.disabled',
} as const satisfies Record<OrganState, string>;
