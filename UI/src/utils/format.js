export function bytesToHuman(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const idx = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  const scaled = value / Math.pow(1024, idx);
  const precision = idx === 0 ? 0 : scaled < 10 ? 2 : 1;
  return `${scaled.toFixed(precision)} ${units[idx]}`;
}
