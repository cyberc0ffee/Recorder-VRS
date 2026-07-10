export function formatBytes(value) {
  if (value === null || value === undefined) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  return `${Number(value).toFixed(1)}%`;
}

export function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(new Date(value));
}

export function hostFromUrl(value) {
  try {
    return new URL(value).host;
  } catch {
    return value || "-";
  }
}

