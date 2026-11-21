const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

// The backend refuses state-changing requests without this header (CSRF protection).
const CSRF_HEADERS = { "X-Requested-With": "rtsp-recorder" };

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// Called on any 401, so the app can show the login page when the session expires.
let onUnauthorized = () => {};
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...CSRF_HEADERS,
      ...(options.headers || {})
    }
  });

  if (response.status === 204) {
    return null;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/login")) {
      onUnauthorized();
    }
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg).join("; ")
      : payload.detail;
    throw new ApiError(detail || `Request failed with status ${response.status}`, response.status);
  }
  return payload;
}

const post = (path, body) =>
  request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  login: (username, password) => post("/auth/login", { username, password }),
  logout: () => post("/auth/logout"),
  me: () => request("/auth/me"),
  changePassword: (currentPassword, newPassword) =>
    post("/auth/password", { current_password: currentPassword, new_password: newPassword }),

  listCameras: () => request("/cameras"),
  createCamera: (payload) => post("/cameras", payload),
  updateCamera: (cameraId, payload) =>
    request(`/cameras/${cameraId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCamera: (cameraId, deleteRecordings = false) =>
    request(`/cameras/${cameraId}?delete_recordings=${deleteRecordings}`, { method: "DELETE" }),
  startCamera: (cameraId) => post(`/cameras/${cameraId}/start`),
  stopCamera: (cameraId) => post(`/cameras/${cameraId}/stop`),

  listAllRecordings: ({ cameraId = null, start = null, end = null, limit = 500 } = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cameraId) params.set("camera_id", String(cameraId));
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    return request(`/recordings?${params.toString()}`);
  },
  deleteRecording: (recordingId) => request(`/recordings/${recordingId}`, { method: "DELETE" }),
  recordingDownloadUrl: (recordingId) => `${API_BASE_URL}/recordings/${recordingId}/download`,
  recordingPlayUrl: (recordingId) => `${API_BASE_URL}/recordings/${recordingId}/play`,

  getSystem: () => request("/system"),
  listEvents: (limit = 100) => request(`/events?limit=${limit}`),
  runCleanup: () => post("/cleanup")
};
