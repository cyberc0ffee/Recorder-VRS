import { defineStore } from "pinia";

import { api } from "../api/client";

export const useRecorderStore = defineStore("recorder", {
  state: () => ({
    user: null,
    authChecked: false,
    cameras: [],
    recordings: [],
    events: [],
    system: null,
    loading: false,
    saving: false,
    error: null,
    errorFromPolling: false
  }),
  getters: {
    onlineCameras: (state) => state.cameras.filter((camera) => camera.status.online),
    recordingCameras: (state) => state.cameras.filter((camera) => camera.status.recording),
    offlineCameras: (state) => state.cameras.filter((camera) => !camera.status.online)
  },
  actions: {
    async checkAuth() {
      try {
        this.user = await api.me();
      } catch {
        this.user = null;
      } finally {
        this.authChecked = true;
      }
    },
    async login(username, password) {
      this.user = await api.login(username, password);
      this.error = null;
    },
    async logout() {
      try {
        await api.logout();
      } finally {
        this.sessionExpired();
      }
    },
    sessionExpired() {
      this.user = null;
      this.cameras = [];
      this.recordings = [];
      this.events = [];
      this.system = null;
    },
    async changePassword(currentPassword, newPassword) {
      await api.changePassword(currentPassword, newPassword);
      // the backend closes every session after a password change
      this.sessionExpired();
    },
    async run(action) {
      this.error = null;
      this.errorFromPolling = false;
      try {
        return await action();
      } catch (error) {
        if (error.status !== 401) this.error = error.message;
        throw error;
      }
    },
    async refreshAll() {
      if (!this.user) return;
      this.loading = true;
      try {
        const [cameras, system, events] = await Promise.all([
          api.listCameras(),
          api.getSystem(),
          api.listEvents(8)
        ]);
        this.cameras = cameras;
        this.system = system;
        this.events = events;
        // a successful poll clears only its own errors, never the error of a failed action
        if (this.errorFromPolling) {
          this.error = null;
          this.errorFromPolling = false;
        }
      } catch (error) {
        if (error.status !== 401 && (!this.error || this.errorFromPolling)) {
          this.error = error.message;
          this.errorFromPolling = true;
        }
      } finally {
        this.loading = false;
      }
    },
    async refreshCameras() {
      this.cameras = await this.run(() => api.listCameras());
    },
    async refreshEvents(limit = 100) {
      this.events = await this.run(() => api.listEvents(limit));
    },
    async refreshRecordings(filters = {}) {
      this.recordings = await this.run(() => api.listAllRecordings(filters));
    },
    async createCamera(payload) {
      this.saving = true;
      try {
        await this.run(() => api.createCamera(payload));
        await this.refreshAll();
      } finally {
        this.saving = false;
      }
    },
    async updateCamera(cameraId, payload) {
      this.saving = true;
      try {
        await this.run(() => api.updateCamera(cameraId, payload));
        await this.refreshAll();
      } finally {
        this.saving = false;
      }
    },
    async deleteCamera(cameraId, deleteRecordings = false) {
      await this.run(() => api.deleteCamera(cameraId, deleteRecordings));
      await this.refreshAll();
    },
    async startCamera(cameraId) {
      await this.run(() => api.startCamera(cameraId)).catch(() => {});
      await this.refreshAll();
    },
    async stopCamera(cameraId) {
      await this.run(() => api.stopCamera(cameraId)).catch(() => {});
      await this.refreshAll();
    },
    async runCleanup() {
      const result = await this.run(() => api.runCleanup());
      await this.refreshAll();
      return result;
    },
    async deleteRecording(recordingId) {
      await this.run(() => api.deleteRecording(recordingId));
    }
  }
});
