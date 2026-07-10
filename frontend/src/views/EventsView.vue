<template>
  <section class="section-block">
    <div class="section-heading">
      <h2>Event Log</h2>
      <button class="secondary-button" type="button" @click="store.refreshEvents(100)">
        <RefreshCw :size="17" />
        <span>Refresh</span>
      </button>
    </div>

    <div class="event-list full">
      <article v-for="event in store.events" :key="event.id" class="event-row">
        <StatusPill :label="event.level" :variant="levelVariant(event.level)" />
        <div>
          <p>{{ event.message }}</p>
          <time>{{ formatDate(event.timestamp) }}</time>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted } from "vue";
import { RefreshCw } from "lucide-vue-next";

import StatusPill from "../components/StatusPill.vue";
import { useRecorderStore } from "../stores/recorder";
import { formatDate } from "../utils/formatters";

const store = useRecorderStore();

function levelVariant(level) {
  if (level === "ERROR" || level === "CRITICAL") return "danger";
  if (level === "WARNING") return "warning";
  if (level === "INFO") return "info";
  return "neutral";
}

onMounted(() => store.refreshEvents(100));
</script>

