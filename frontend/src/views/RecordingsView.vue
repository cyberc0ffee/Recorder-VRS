<template>
  <div class="view-stack">
    <section class="editor-band">
      <div class="recording-toolbar">
        <label>
          <span>Camera</span>
          <select v-model="selectedCameraId" @change="loadRecordings">
            <option value="">All cameras</option>
            <option v-for="camera in store.cameras" :key="camera.id" :value="camera.id">
              {{ camera.name }}
            </option>
          </select>
        </label>

        <button class="secondary-button" type="button" @click="loadRecordings">
          <RefreshCw :size="17" />
          <span>Refresh</span>
        </button>
      </div>
    </section>

    <section v-if="selectedRecording" class="section-block">
      <div class="section-heading">
        <h2>{{ fileName(selectedRecording.filename) }}</h2>
        <a class="secondary-button" :href="downloadUrl(selectedRecording.id)">
          <Download :size="17" />
          <span>Download</span>
        </a>
      </div>
      <video class="recording-player" :src="streamUrl(selectedRecording.id)" controls></video>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>Recording Browser</h2>
        <button class="secondary-button" type="button" @click="runCleanup">
          <Trash2 :size="17" />
          <span>Cleanup</span>
        </button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Camera</th>
              <th>Start</th>
              <th>Size</th>
              <th class="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="recording in store.recordings" :key="recording.id">
              <td>
                <strong>{{ fileName(recording.filename) }}</strong>
                <small>{{ recording.filename }}</small>
              </td>
              <td>{{ cameraName(recording.camera_id) }}</td>
              <td>{{ formatDate(recording.start_time || recording.end_time) }}</td>
              <td>{{ formatBytes(recording.size) }}</td>
              <td>
                <div class="row-actions">
                  <button class="icon-button" type="button" title="Play" @click="selectedRecording = recording">
                    <Play :size="17" />
                  </button>
                  <a class="icon-button" title="Download" :href="downloadUrl(recording.id)">
                    <Download :size="17" />
                  </a>
                  <button class="icon-button danger-button" type="button" title="Delete" @click="deleteRecording(recording)">
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
import { onMounted, ref } from "vue";
import { Download, Play, RefreshCw, Trash2 } from "lucide-vue-next";

import { api } from "../api/client";
import { useRecorderStore } from "../stores/recorder";
import { formatBytes, formatDate } from "../utils/formatters";

const store = useRecorderStore();
const selectedCameraId = ref("");
const selectedRecording = ref(null);

function fileName(path) {
  return path?.split(/[\\/]/).pop() || "-";
}

function cameraName(cameraId) {
  return store.cameras.find((camera) => camera.id === cameraId)?.name || `#${cameraId}`;
}

function downloadUrl(recordingId) {
  return api.recordingDownloadUrl(recordingId);
}

function streamUrl(recordingId) {
  return api.recordingStreamUrl(recordingId);
}

async function loadRecordings() {
  const cameraId = selectedCameraId.value ? Number(selectedCameraId.value) : null;
  await store.refreshRecordings(cameraId);
}

async function runCleanup() {
  await store.runCleanup();
  await loadRecordings();
}

async function deleteRecording(recording) {
  const confirmed = window.confirm(`Delete recording "${fileName(recording.filename)}"?`);
  if (confirmed) {
    await store.deleteRecording(recording.id);
    await loadRecordings();
    if (selectedRecording.value?.id === recording.id) {
      selectedRecording.value = null;
    }
  }
}

onMounted(async () => {
  if (!store.cameras.length) {
    await store.refreshAll();
  }
  await loadRecordings();
});
</script>

