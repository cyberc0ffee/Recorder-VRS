import { defineStore } from "pinia";

import { api } from "../api/client";

export const useRecorderStore = defineStore("recorder", {
  state: () => ({
    cameras: [],
    recordings: [],
    events: [],
    system: null,
    loading: false,
    saving: false,
    error: null
  }),
  getters: {
    onlineCameras: (state) => state.cameras.filter((camera) => camera.status.online),
    recordingCameras: (state) => state.cameras.filter((camera) => camera.status.recording),
    offlineCameras: (state) => state.cameras.filter((camera) => !camera.status.online)
  },
  actions: {
    async refreshAll() {
      this.loading = true;
      this.error = null;
      try {
        const [cameras, system, events] = await Promise.all([
          api.listCameras(),
          api.getSystem(),
          api.listEvents(8)
        ]);
        this.cameras = cameras;
        this.system = system;
        this.events = events;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async refreshCameras() {
      this.cameras = await api.listCameras();
    },
    async refreshEvents(limit = 100) {
      this.events = await api.listEvents(limit);
    },
    async refreshRecordings(cameraId = null) {
      this.recordings = await api.listAllRecordings(cameraId, 500);
    },
    async createCamera(payload) {
      this.saving = true;
      try {
        await api.createCamera(payload);
        await this.refreshAll();
      } finally {
        this.saving = false;
      }
    },
    async updateCamera(cameraId, payload) {
      this.saving = true;
      try {
        await api.updateCamera(cameraId, payload);
        await this.refreshAll();
      } finally {
        this.saving = false;
      }
    },
    async deleteCamera(cameraId) {
      await api.deleteCamera(cameraId);
      await this.refreshAll();
    },
    async startCamera(cameraId) {
      await api.startCamera(cameraId);
      await this.refreshAll();
    },
    async stopCamera(cameraId) {
      await api.stopCamera(cameraId);
      await this.refreshAll();
    },
    async runCleanup() {
      const result = await api.runCleanup();
      await this.refreshAll();
      return result;
    },
    async deleteRecording(recordingId) {
      await api.deleteRecording(recordingId);
      await this.refreshRecordings();
    }
  }
});
