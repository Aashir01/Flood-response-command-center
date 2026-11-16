import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTRACT_VERSION } from '@/gen/contracts';

const root = resolve(__dirname, '..', '..', '..');

describe('generated contract types', () => {
  it('header version equals contracts.lock.json', () => {
    const lock = JSON.parse(readFileSync(resolve(root, 'packages/stitch_common/contracts.lock.json'), 'utf8')) as { contract_version: string };
    expect(CONTRACT_VERSION).toBe(lock.contract_version);
    const src = readFileSync(resolve(__dirname, '..', '..', 'src/gen/contracts.ts'), 'utf8');
    expect(src).toContain(`// CONTRACT_VERSION: ${lock.contract_version}`);
  });
});
