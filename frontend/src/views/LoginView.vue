<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <div class="brand-block">
        <div class="brand-mark">R</div>
        <div>
          <div class="brand-title">RTSP Recorder</div>
          <div class="brand-subtitle">Sign in to the NVR console</div>
        </div>
      </div>

      <label>
        <span>Username</span>
        <input v-model.trim="username" autocomplete="username" required />
      </label>
      <label>
        <span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>

      <div v-if="error" class="alert">{{ error }}</div>

      <button class="primary-button" type="submit" :disabled="busy">
        <LogIn :size="17" />
        <span>Sign in</span>
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { LogIn } from "lucide-vue-next";

import { useRecorderStore } from "../stores/recorder";

const store = useRecorderStore();
const username = ref("admin");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await store.login(username.value, password.value);
    password.value = "";
  } catch (exc) {
    error.value = exc.message;
  } finally {
    busy.value = false;
  }
}
</script>
