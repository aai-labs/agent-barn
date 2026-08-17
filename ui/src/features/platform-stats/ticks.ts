const TARGET_TICKS = 8;

/**
 * Evenly spaced x-axis ticks with a constant stride.
 *
 * Picking ticks by rounding `i * (n-1)/(TARGET-1)` can land two of them on
 * adjacent days — at 14 points it produces Aug 4 and Aug 5 side by side and the
 * labels collide. A fixed stride keeps every gap identical and never adjacent
 * unless the series is short enough to label in full.
 */
export function evenlySpacedTicks(dates: string[]): string[] {
  if (dates.length <= TARGET_TICKS) return dates;

  const stride = Math.ceil(dates.length / TARGET_TICKS);
  const ticks: string[] = [];
  for (let i = 0; i < dates.length; i += stride) {
    ticks.push(dates[i]);
  }
  return ticks;
}
