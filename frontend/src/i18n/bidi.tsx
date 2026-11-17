import type { ReactNode } from 'react';

/**
 * Bidi isolation for identifiers, units, numbers with units, JSON pointers, run ids and citations.
 * `ltr` forces left-to-right (pointers, ids, URLs); otherwise the browser picks the direction from content.
 */
export function Bdi({ children, ltr = false, className }: { children: ReactNode; ltr?: boolean; className?: string }) {
  return (
    <bdi dir={ltr ? 'ltr' : undefined} className={className} data-bdi="">
      {children}
    </bdi>
  );
}
