<template>
  <div class="view-stack">
    <section class="metrics-grid">
      <MetricTile :icon="Cpu" label="CPU" :value="formatPercent(system?.cpu_percent)" />
      <MetricTile :icon="MemoryStick" label="RAM" :value="formatPercent(system?.ram?.percent)" />
      <MetricTile :icon="HardDrive" label="Disk Free" :value="formatBytes(system?.disk?.free_bytes)" />
      <MetricTile :icon="Radio" label="Recording" :value="system?.recording_cameras ?? 0" />
      <MetricTile :icon="Wifi" label="Online" :value="system?.cameras_online ?? 0" />
      <MetricTile :icon="WifiOff" label="Offline" :value="system?.cameras_offline ?? 0" />
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>Cameras</h2>
        <RouterLink class="text-button" to="/cameras">Manage</RouterLink>
      </div>

      <div class="camera-summary-grid">
        <article v-for="camera in store.cameras" :key="camera.id" class="camera-summary">
          <div>
            <h3>{{ camera.name }}</h3>
            <p>{{ hostFromUrl(camera.rtsp_url) }}</p>
          </div>
          <StatusPill
            :label="camera.status.recording ? 'Recording' : camera.status.online ? 'Online' : 'Offline'"
            :variant="camera.status.recording ? 'success' : camera.status.online ? 'info' : 'danger'"
          />
        </article>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>Recent Events</h2>
        <RouterLink class="text-button" to="/events">Open</RouterLink>
      </div>

      <div class="event-list">
        <article v-for="event in store.events" :key="event.id" class="event-row">
          <StatusPill :label="event.level" :variant="event.level === 'ERROR' ? 'danger' : event.level === 'WARNING' ? 'warning' : 'neutral'" />
          <div>
            <p>{{ event.message }}</p>
            <time>{{ formatDate(event.timestamp) }}</time>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { Cpu, HardDrive, MemoryStick, Radio, Wifi, WifiOff } from "lucide-vue-next";

import MetricTile from "../components/MetricTile.vue";
import StatusPill from "../components/StatusPill.vue";
import { useRecorderStore } from "../stores/recorder";
import { formatBytes, formatDate, formatPercent, hostFromUrl } from "../utils/formatters";

const store = useRecorderStore();
const system = computed(() => store.system);
</script>

