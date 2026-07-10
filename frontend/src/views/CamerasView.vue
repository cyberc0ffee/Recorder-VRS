<template>
  <div class="view-stack">
    <section class="editor-band">
      <form class="camera-form" @submit.prevent="submitCamera">
        <label>
          <span>Name</span>
          <input v-model.trim="form.name" required maxlength="120" placeholder="Entrance" />
        </label>

        <label class="url-field">
          <span>RTSP URL</span>
          <input v-model.trim="form.rtsp_url" required placeholder="rtsp://user:pass@192.168.1.20:554/stream1" />
        </label>

        <label class="toggle-line">
          <input v-model="form.enabled" type="checkbox" />
          <span>Enabled</span>
        </label>

        <label class="toggle-line">
          <input v-model="form.autostart" type="checkbox" />
          <span>Autostart</span>
        </label>

        <div class="form-actions">
          <button class="primary-button" type="submit" :disabled="store.saving">
            <Save :size="17" />
            <span>{{ editingCameraId ? "Save" : "Add" }}</span>
          </button>
          <button v-if="editingCameraId" class="secondary-button" type="button" @click="resetForm">
            <X :size="17" />
            <span>Cancel</span>
          </button>
        </div>
      </form>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>Camera Fleet</h2>
        <button class="secondary-button" type="button" @click="store.refreshCameras">
          <RefreshCw :size="17" />
          <span>Refresh</span>
        </button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Host</th>
              <th>Status</th>
              <th>Restarts</th>
              <th>Last Error</th>
              <th class="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="camera in store.cameras" :key="camera.id">
              <td>
                <strong>{{ camera.name }}</strong>
                <small>{{ camera.enabled ? "enabled" : "disabled" }} · {{ camera.autostart ? "autostart" : "manual" }}</small>
              </td>
              <td>{{ hostFromUrl(camera.rtsp_url) }}</td>
              <td>
                <StatusPill
                  :label="camera.status.recording ? 'Recording' : camera.status.online ? 'Online' : 'Offline'"
                  :variant="camera.status.recording ? 'success' : camera.status.online ? 'info' : 'danger'"
                />
              </td>
              <td>{{ camera.status.restart_count }}</td>
              <td class="error-cell">{{ camera.status.last_error || "-" }}</td>
              <td>
                <div class="row-actions">
                  <button class="icon-button" type="button" title="Start" @click="store.startCamera(camera.id)">
                    <Play :size="17" />
                  </button>
                  <button class="icon-button" type="button" title="Stop" @click="store.stopCamera(camera.id)">
                    <Square :size="17" />
                  </button>
                  <button class="icon-button" type="button" title="Edit" @click="editCamera(camera)">
                    <Pencil :size="17" />
                  </button>
                  <button class="icon-button danger-button" type="button" title="Delete" @click="deleteCamera(camera)">
                    <Trash2 :size="17" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { Pencil, Play, RefreshCw, Save, Square, Trash2, X } from "lucide-vue-next";

import StatusPill from "../components/StatusPill.vue";
import { useRecorderStore } from "../stores/recorder";
import { hostFromUrl } from "../utils/formatters";

const store = useRecorderStore();
const editingCameraId = ref(null);
const form = reactive({
  name: "",
  rtsp_url: "",
  enabled: true,
  autostart: true
});

function resetForm() {
  editingCameraId.value = null;
  form.name = "";
  form.rtsp_url = "";
  form.enabled = true;
  form.autostart = true;
}

function editCamera(camera) {
  editingCameraId.value = camera.id;
  form.name = camera.name;
  form.rtsp_url = camera.rtsp_url;
  form.enabled = camera.enabled;
  form.autostart = camera.autostart;
}

async function submitCamera() {
  const payload = {
    name: form.name,
    rtsp_url: form.rtsp_url,
    enabled: form.enabled,
    autostart: form.autostart
  };
  if (editingCameraId.value) {
    await store.updateCamera(editingCameraId.value, payload);
  } else {
    await store.createCamera(payload);
  }
  resetForm();
}

async function deleteCamera(camera) {
  const confirmed = window.confirm(`Delete camera "${camera.name}"?`);
  if (confirmed) {
    await store.deleteCamera(camera.id);
  }
}
</script>

