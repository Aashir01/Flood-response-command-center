/** Maximum number of onsets inside any sliding window of `windowMs` (inclusive start, exclusive end). */
export function maxOnsetsInWindow(onsets: number[], windowMs = 1000): number {
  const sorted = [...onsets].sort((a, b) => a - b);
  let best = 0;
  let lo = 0;
  for (let hi = 0; hi < sorted.length; hi++) {
    while ((sorted[hi] as number) - (sorted[lo] as number) >= windowMs) lo++;
    best = Math.max(best, hi - lo + 1);
  }
  return best;
}

/** Reference implementation used by the property test. */
export function bruteForceMaxOnsets(onsets: number[], windowMs = 1000): number {
  let best = 0;
  for (const start of onsets) {
    let n = 0;
    for (const t of onsets) if (t >= start && t < start + windowMs) n++;
    best = Math.max(best, n);
  }
  return best;
}