const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  if (response.status === 204) {
    return null;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed with status ${response.status}`);
  }
  return payload;
}

export const api = {
  listCameras: () => request("/cameras"),
  createCamera: (payload) =>
    request("/cameras", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateCamera: (cameraId, payload) =>
    request(`/cameras/${cameraId}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  deleteCamera: (cameraId) =>
    request(`/cameras/${cameraId}`, {
      method: "DELETE"
    }),
  startCamera: (cameraId) =>
    request(`/cameras/${cameraId}/start`, {
      method: "POST"
    }),
  stopCamera: (cameraId) =>
    request(`/cameras/${cameraId}/stop`, {
      method: "POST"
    }),
  listRecordings: (cameraId) => request(`/cameras/${cameraId}/recordings`),
  listAllRecordings: (cameraId = null, limit = 500) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cameraId) params.set("camera_id", String(cameraId));
    return request(`/recordings?${params.toString()}`);
  },
  deleteRecording: (recordingId) =>
    request(`/recordings/${recordingId}`, {
      method: "DELETE"
    }),
  recordingDownloadUrl: (recordingId) => `${API_BASE_URL}/recordings/${recordingId}/download`,
  recordingStreamUrl: (recordingId) => `${API_BASE_URL}/recordings/${recordingId}/stream`,
  getSystem: () => request("/system"),
  listEvents: (limit = 100) => request(`/events?limit=${limit}`),
  runCleanup: () =>
    request("/cleanup", {
      method: "POST"
    })
};
