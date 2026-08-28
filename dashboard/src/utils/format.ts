/**
 * Format bytes into human-readable string (KB, MB, GB, etc.)
 */
export function fmtBytes(b: number | undefined | null): string {
  if (b === undefined || b === null) return '0 B';
  if (b >= 1e9) return `${(b / 1e9).toFixed(2)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(1)} KB`;
  return `${b} B`;
}
