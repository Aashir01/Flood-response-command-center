import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: ['out/**', '.next/**', 'node_modules/**', 'src/gen/**', 'next-env.d.ts', 'playwright-report/**', 'test-results/**', 'public/worklets/**'],
  },
  {
    rules: {
      // Only motion/registry.ts may declare raw animations (flash-rate test inspects the registry).
      'no-restricted-imports': ['error', { paths: [{ name: 'motion/react', importNames: ['motion'], message: 'Use the lazy `m` component inside LazyMotion.' }] }],
    },
  },
];
export default config;