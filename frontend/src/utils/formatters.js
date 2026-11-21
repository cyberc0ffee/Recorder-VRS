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

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(Number(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function hostFromUrl(value) {
  try {
    return new URL(value).host;
  } catch {
    return value || "-";
  }
}

const STATES = {
  recording: { label: "Recording", variant: "success" },
  starting: { label: "Connecting", variant: "info" },
  reconnecting: { label: "Reconnecting", variant: "warning" },
  stopped: { label: "Stopped", variant: "neutral" }
};

export function cameraState(status) {
  return STATES[status?.state] || { label: "Offline", variant: "danger" };
}
