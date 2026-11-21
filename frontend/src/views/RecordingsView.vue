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

        <label>
          <span>Day</span>
          <input v-model="selectedDay" type="date" @change="loadRecordings" />
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
        <div class="row-actions">
          <a class="secondary-button" :href="downloadUrl(selectedRecording.id)">
            <Download :size="17" />
            <span>Download MKV</span>
          </a>
          <button class="icon-button" type="button" title="Close" @click="selectedRecording = null">
            <X :size="17" />
          </button>
        </div>
      </div>
      <!-- MKV is remuxed to MP4 by the server (no transcoding), so every browser can play it -->
      <video
        :key="selectedRecording.id"
        class="recording-player"
        :src="playUrl(selectedRecording.id)"
        controls
        autoplay
        @error="playerError = true"
      ></video>
      <p v-if="playerError" class="muted">
        The browser cannot play this video (H.265 is not supported by most browsers): download the MKV
        and open it with VLC.
      </p>
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
              <th>Duration</th>
              <th>Size</th>
              <th class="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!store.recordings.length">
              <td colspan="6" class="muted">No recordings for this selection.</td>
            </tr>
            <tr v-for="recording in store.recordings" :key="recording.id">
              <td>
                <strong>{{ fileName(recording.filename) }}</strong>
              </td>
              <td>{{ cameraName(recording.camera_id) }}</td>
              <td>{{ formatDate(recording.start_time || recording.end_time) }}</td>
              <td>{{ formatDuration(recording.duration) }}</td>
              <td>{{ formatBytes(recording.size) }}</td>
              <td>
                <div class="row-actions">
                  <button class="icon-button" type="button" title="Play" @click="play(recording)">
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
import { Download, Play, RefreshCw, Trash2, X } from "lucide-vue-next";

import { api } from "../api/client";
import { useRecorderStore } from "../stores/recorder";
import { formatBytes, formatDate, formatDuration } from "../utils/formatters";

const store = useRecorderStore();
const selectedCameraId = ref("");
const selectedDay = ref("");
const selectedRecording = ref(null);
const playerError = ref(false);

function fileName(path) {
  return path?.split(/[\\/]/).pop() || "-";
}

function cameraName(cameraId) {
  return store.cameras.find((camera) => camera.id === cameraId)?.name || `#${cameraId}`;
}

function downloadUrl(recordingId) {
  return api.recordingDownloadUrl(recordingId);
}

function playUrl(recordingId) {
  return api.recordingPlayUrl(recordingId);
}

function play(recording) {
  playerError.value = false;
  selectedRecording.value = recording;
}

function dayRange(day) {
  if (!day) return {};
  // the day is local time: the API receives the corresponding UTC instants
  const start = new Date(`${day}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start: start.toISOString(), end: end.toISOString() };
}

async function loadRecordings() {
  const cameraId = selectedCameraId.value ? Number(selectedCameraId.value) : null;
  await store.refreshRecordings({ cameraId, ...dayRange(selectedDay.value) }).catch(() => {});
}

async function runCleanup() {
  await store.runCleanup().catch(() => {});
  await loadRecordings();
}

async function deleteRecording(recording) {
  if (!window.confirm(`Delete recording "${fileName(recording.filename)}"?`)) return;
  await store.deleteRecording(recording.id).catch(() => {});
  if (selectedRecording.value?.id === recording.id) {
    selectedRecording.value = null;
  }
  await loadRecordings();
}

onMounted(async () => {
  if (!store.cameras.length) {
    await store.refreshAll();
  }
  await loadRecordings();
});
</script>
