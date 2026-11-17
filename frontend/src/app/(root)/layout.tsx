import type { ReactNode } from 'react';

// Root layout for the redirect page only; each language has its own root layout in [lang]/layout.tsx.
export default function RootRedirectLayout({ children }: { children: ReactNode }) {
  return children;
}
