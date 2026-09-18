export function fmtScore(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}
