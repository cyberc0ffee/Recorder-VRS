<template>
  <div v-if="!store.authChecked" class="login-shell">
    <p class="muted">Loading…</p>
  </div>

  <LoginView v-else-if="!store.user" />

  <div v-else class="app-shell">
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
        <RouterLink to="/account">
          <KeyRound :size="18" />
          <span>Account</span>
        </RouterLink>
      </nav>
    </aside>

    <main class="content-shell">
      <header class="topbar">
        <div>
          <h1>{{ routeTitle }}</h1>
          <p>{{ currentDate }}</p>
        </div>
        <div class="row-actions">
          <button class="icon-button" type="button" title="Refresh" @click="store.refreshAll">
            <RefreshCw :size="18" />
          </button>
          <button class="secondary-button" type="button" title="Log out" @click="store.logout">
            <LogOut :size="17" />
            <span>{{ store.user.username }}</span>
          </button>
        </div>
      </header>

      <div v-if="store.error" class="alert">
        {{ store.error }}
      </div>

      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import {
  Camera,
  FileVideo,
  KeyRound,
  LayoutDashboard,
  ListTree,
  LogOut,
  RefreshCw
} from "lucide-vue-next";

import { setUnauthorizedHandler } from "./api/client";
import { useRecorderStore } from "./stores/recorder";
import LoginView from "./views/LoginView.vue";

const store = useRecorderStore();
const route = useRoute();
let timer = null;

const currentDate = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short"
}).format(new Date());

const routeTitle = computed(() => {
  if (route.name === "cameras") return "Camera Management";
  if (route.name === "recordings") return "Recordings";
  if (route.name === "events") return "Events";
  if (route.name === "account") return "Account";
  return "Dashboard";
});

// polling runs only while someone is logged in
watch(
  () => store.user,
  (user) => {
    window.clearInterval(timer);
    timer = null;
    if (user) {
      store.refreshAll();
      timer = window.setInterval(() => store.refreshAll(), 10000);
    }
  }
);

onMounted(async () => {
  setUnauthorizedHandler(() => store.sessionExpired());
  await store.checkAuth();
});

onUnmounted(() => window.clearInterval(timer));
</script>
