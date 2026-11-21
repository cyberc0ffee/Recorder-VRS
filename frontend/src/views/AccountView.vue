<template>
  <section class="editor-band">
    <form class="camera-form" @submit.prevent="submit">
      <label>
        <span>Current password</span>
        <input v-model="current" type="password" autocomplete="current-password" required />
      </label>
      <label>
        <span>New password (at least 10 characters)</span>
        <input v-model="next" type="password" autocomplete="new-password" minlength="10" required />
      </label>
      <label>
        <span>Repeat new password</span>
        <input v-model="repeat" type="password" autocomplete="new-password" minlength="10" required />
      </label>
      <div class="form-actions">
        <button class="primary-button" type="submit" :disabled="busy">
          <KeyRound :size="17" />
          <span>Change password</span>
        </button>
      </div>
    </form>
    <div v-if="error" class="alert">{{ error }}</div>
    <p class="muted">After the change every open session is closed and you sign in again.</p>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { KeyRound } from "lucide-vue-next";

import { useRecorderStore } from "../stores/recorder";

const store = useRecorderStore();
const current = ref("");
const next = ref("");
const repeat = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  if (next.value !== repeat.value) {
    error.value = "The new passwords do not match";
    return;
  }
  busy.value = true;
  try {
    await store.changePassword(current.value, next.value);
  } catch (exc) {
    error.value = exc.message;
  } finally {
    busy.value = false;
  }
}
</script>
