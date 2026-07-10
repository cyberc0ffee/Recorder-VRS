<template>
  <section class="metric-tile">
    <div class="metric-icon">
      <component :is="icon" :size="20" />
    </div>
    <div>
      <div class="metric-label">{{ label }}</div>
      <div class="metric-value">{{ value }}</div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  icon: {
    type: Object,
    required: true
  },
  label: {
    type: String,
    required: true
  },
  value: {
    type: [String, Number],
    required: true
  }
});
</script>

