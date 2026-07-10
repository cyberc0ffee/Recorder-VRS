<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="brand-mark">R</div>
        <div>
          <div class="brand-title">RTSP Recorder</div>
          <div class="brand-subtitle">NVR Console</div>
        </div>
      </div>

      <nav class="main-nav" aria-label="Primary">
        <RouterLink to="/">
          <LayoutDashboard :size="18" />
          <span>Dashboard</span>
        </RouterLink>
        <RouterLink to="/cameras">
          <Camera :size="18" />
          <span>Cameras</span>
        </RouterLink>
        <RouterLink to="/recordings">
          <FileVideo :size="18" />
          <span>Recordings</span>
        </RouterLink>
        <RouterLink to="/events">
          <ListTree :size="18" />
          <span>Events</span>
        </RouterLink>
      </nav>
    </aside>

    <main class="content-shell">
      <header class="topbar">
        <div>
          <h1>{{ routeTitle }}</h1>
          <p>{{ currentDate }}</p>
        </div>
        <button class="icon-button" type="button" title="Refresh" @click="store.refreshAll">
          <RefreshCw :size="18" />
        </button>
      </header>

      <div v-if="store.error" class="alert">
        {{ store.error }}
      </div>

      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { Camera, FileVideo, LayoutDashboard, ListTree, RefreshCw } from "lucide-vue-next";

import { useRecorderStore } from "./stores/recorder";

const store = useRecorderStore();
const route = useRoute();

const currentDate = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short"
}).format(new Date());

const routeTitle = computed(() => {
  if (route.name === "cameras") return "Camera Management";
  if (route.name === "recordings") return "Recordings";
  if (route.name === "events") return "Events";
  return "Dashboard";
});

onMounted(() => {
  store.refreshAll();
  window.setInterval(() => store.refreshAll(), 15000);
});
</script>
